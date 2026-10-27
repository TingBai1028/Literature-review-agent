"""5. Gap finder agent. Spec: docs/agents/gap_finder.md

A gap is a pair of papers in one cluster that are close enough to plausibly combine, but that nothing in the
literature has combined yet. Four stages, each writing one trace line per kept or dropped item:
1. candidate_pairs (code): similarity band, no citation between the two, no retrieved paper citing both;
2. gap writer (LLM): claim / grounds / warrant, with both quotes checked against the original text;
3. coverage search: cached/budgeted OpenAlex (Semantic Scholar fallback with a key), then the LLM checks the results;
4. grading agent (LLM): SGHA labels; keeps novel and known_open, ranks and caps per cluster.
Optional (gap_explicit_enabled): gaps the authors state themselves skip stages 1 and 2.
"""

from __future__ import annotations

import itertools
import logging
import threading
import os
import re
import time
from collections import defaultdict

from litagent.agents.connection_finder import first_sentence
from litagent.cluster_cards import compact
from litagent.cluster_state import digest
from litagent.config import Settings
from litagent.finding_engine import (FindingContext, cache_key, cached, check_deadline, merge_record, now, prepare,
    request, resolve_evidence, sources)
from litagent.integrations.llm import halve_on_timeout
from litagent.schemas import (Cluster, Connection, CoverageJudgements, CoverageSearch, Evidence, ExplicitGapDrafts,
    FindingAudit, FindingCacheRecord, FindingDependency, Gap, GapCoverage, GapDrafts, GapLabelDecisions, Paper,
    SearchCriteria)
from litagent.parallel import run_parallel
from litagent.sample_data import sample_similarity
from litagent.tools.openalex import OpenAlexError, search_openalex
from litagent.tools.semantic_scholar import SemanticScholarError, search_semantic_scholar
from litagent.tools.search_store import SearchBudget, SearchLimitError
from litagent.trace import current_trace, mask

KEPT_LABELS = ("novel", "known_open")
COVERAGE_SCOPE = "Top results of budgeted OpenAlex queries (Semantic Scholar fallback with a key); cached results may be reused. This does not establish global novelty."
_EXPLICIT_CUE = re.compile(r"remains? (?:unknown|unclear|unexplored|open)|future (?:work|research)|"
                           r"ha(?:s|ve) not (?:yet )?been (?:studied|explored|investigated|addressed)", re.IGNORECASE)

# "SFT" or "fine-tuning" alone does not establish which parameters were trained (NusaMT-7B
# says SFT in its abstract but uses LoRA in its full text). A claim may only assert this
# scope when a supplied source of the pair states it.
_FULL_PARAMETER = re.compile(r"\bfull(?:[- ]parameter|[- ]model|[- ]weight)s?\b|\bfull[- ]?(?:fine[- ]?tun\w*|sft)\b"
                             r"|全参数|全量(?:微调|参数)", re.IGNORECASE)


def unsupported_scope_claims(texts: list[str], sources: list[dict]) -> list[str]:
    """Parameter-scope terms in a claim that no supplied source span of the pair states."""
    found = {m.group() for text in texts for m in _FULL_PARAMETER.finditer(text)}
    stated = any(_FULL_PARAMETER.search(span["quote"]) for source in sources for span in source["spans"])
    return [] if stated else sorted(found)


def find_gaps(
    papers: list[Paper],
    clusters: list[Cluster],
    connections: list[Connection],
    settings: Settings,
    fix: str | None = None,
    *, context: FindingContext | None = None,
) -> list[Gap]:
    """`fix` is the orchestrator grader's fix after a failed stage grade; the writer applies it to every gap.
    `connections` is accepted for the orchestrator's interface; gaps are written from the papers alone."""
    if settings.sample_mode:
        return _sample_gaps(papers, clusters, settings)

    context = prepare(papers, clusters, settings, context)
    source_map = sources(papers, settings, context)
    candidates = candidate_pairs(papers, clusters, context.similarity, settings, set(source_map))
    report = FindingAudit(stage="gaps", candidate_pairs=len(candidates))
    context.partial_gaps = []
    try:
        if not candidates and not settings.gap_explicit_enabled:
            return []
        key = cache_key("gaps", {"task_version": "gaps-v2", "question": context.question, "fix": fix,
                                 "candidates": candidates, "use_full_text": context.use_full_text,
                                 "clusters": [c.model_dump(mode="json") for c in clusters],
                                 "corpus": [p.model_dump(mode="json") for p in papers],
                                 "output_schema": Gap.model_json_schema()}, GapDrafts, settings)
        record = cached(key, context, settings)
        reused = record is not None
        if record is None:
            record = _Run(papers, source_map, fix, settings, context).assess(candidates, clusters)
            context.cache[key] = record
        # Escalated full text (spec H5) goes back into the caller's papers: the stage grader checks every quote
        # against them, and the saved version keeps them.
        for i, paper in enumerate(papers):
            if paper.id in record.full_text and not paper.full_text:
                papers[i] = paper.model_copy(update={"full_text": record.full_text[paper.id]})
        merge_record(report, record, context, reused=reused)
        context.partial_gaps = [g.model_copy(deep=True) for g in record.gaps]
        return context.partial_gaps
    finally:
        context.audits.append(report)


def candidate_pairs(papers: list[Paper], clusters: list[Cluster], similarity, settings: Settings,
                    quotable: set[str] | None = None) -> list[dict]:
    """Stage 1: pairs within one cluster in the similarity band that the retrieved literature hasn't connected.

    A pair is dropped when one paper cites the other or a retrieved paper cites both. When either paper has no
    reference list the pair is kept with citation_check "unknown". Kept pairs are sorted by similarity and
    capped per cluster before any LLM call. `quotable` limits pairs to papers with text to quote from.
    """
    index = {p.id: i for i, p in enumerate(papers)}
    references = {p.id: None if p.references is None else set(p.references) for p in papers}
    cited_by = defaultdict(set)  # paper id -> retrieved papers that cite it
    for p in papers:
        for ref in references[p.id] or ():
            if ref in index and ref != p.id:
                cited_by[ref].add(p.id)
    cap = settings.gap_max_per_cluster * settings.gap_candidate_multiplier
    low, high = settings.gap_similarity_min, settings.gap_similarity_max
    selected = []
    for cluster in clusters:
        kept, dropped = [], 0
        for a, b in itertools.combinations(sorted(cluster.paper_ids), 2):
            gid, score = _gap_id(a, b), float(similarity[index[a], index[b]])
            if quotable is not None and not {a, b} <= quotable:
                reason = "a paper has no abstract or full text to quote from"
            elif not low <= score <= high:
                reason = f"similarity {score:.3f} is outside {low}-{high}"
            elif a in cited_by[b] or b in cited_by[a]:
                reason = "one paper cites the other"
            elif shared := sorted(cited_by[a] & cited_by[b] - {a, b}):
                reason = f"retrieved paper {shared[0]} already cites both"
            else:
                check = "passed" if references[a] is not None and references[b] is not None else "unknown"
                kept.append({"gap_id": gid, "pair_id": "PAIR-" + gid.removeprefix("GAP-"), "cluster_id": cluster.id,
                             "cluster_ids": [cluster.id], "scope": "within_cluster", "paper_ids": [a, b],
                             "similarity": score, "citation_check": check})
                continue
            dropped += 1
            _log("candidates", gid, "dropped", reason, logging.DEBUG, paper_ids=[a, b], similarity=round(score, 4))
        kept.sort(key=lambda c: (-c["similarity"], c["paper_ids"]))
        for c in kept[cap:]:
            _log("candidates", c["gap_id"], "dropped", f"over the cap of {cap} candidates per cluster", logging.DEBUG,
                 paper_ids=c["paper_ids"], similarity=round(c["similarity"], 4))
        for c in kept[:cap]:
            _log("candidates", c["gap_id"], "kept", f"similarity {c['similarity']:.3f} in band, citation check "
                 f"{c['citation_check']}", logging.DEBUG, paper_ids=c["paper_ids"])
        selected += kept[:cap]
        if trace := current_trace():
            trace.log("gap_finder", "candidate generator", f"{len(kept[:cap])} candidates in {cluster.id}",
                      result={"pairs_checked": len(kept) + dropped, "candidates": len(kept[:cap]),
                              "dropped": dropped + len(kept[cap:])},
                      why=f"Similarity {low}-{high}, no direct or shared citation, at most {cap} per cluster; "
                          "one line per pair is in the trace file", stage="candidates")
    return selected


class _Run:
    """One Gap finder run: stages 2-4 per cluster, with every drop recorded for the trace and the audit."""

    def __init__(self, papers: list[Paper], source_map: dict, fix: str | None, settings: Settings,
                 context: FindingContext | None):
        self.by_id = {p.id: p for p in papers}
        self.source_map, self.fix, self.settings, self.context = source_map, fix, settings, context
        self.fetched: dict[str, str] = {}  # full text read by escalation (spec H5)
        self.escalated: set[str] = set()
        self.lock = threading.Lock()  # clusters run in parallel; shared bookkeeping changes under this lock
        self.outcomes: dict[str, dict] = {}
        self.checked: dict[str, list[str]] = {}  # gap id -> titles the coverage judge saw
        self.coverage_budget = SearchBudget(settings.gap_coverage_max_requests)

    def assess(self, candidates: list[dict], clusters: list[Cluster]) -> FindingCacheRecord:
        for c in candidates:
            self.outcomes[c["gap_id"]] = {**{k: c[k] for k in ("pair_id", "paper_ids", "cluster_ids", "scope")},
                                          "gap_type": "inferred"}
        finished: dict[str, list[Gap]] = {}

        def one(cluster: Cluster) -> list[Gap]:
            mine = [c for c in candidates if c["cluster_id"] == cluster.id]
            found = self.write(cluster, mine, {})
            if self.settings.gap_explicit_enabled:
                found += self.explicit(cluster)
            kept, fixes = self.grade(cluster, self.coverage(found), final=False)
            if fixes:  # One rewrite per flagged gap, as the orchestrator does for a failed stage.
                retried = self.write(cluster, [c for c in mine if c["gap_id"] in fixes], fixes)
                kept += self.grade(cluster, self.coverage(retried), final=True)[0]
            ranked = self.escalate(cluster, self.rank(kept), mine)
            with self.lock:
                finished[cluster.id] = ranked
                # A failure elsewhere keeps the clusters already finished (real run 26 Oct lost 9 finished gaps to
                # one timeout), in cluster order whatever order they finish in.
                self.context.partial_gaps = [g.model_copy(deep=True) for c in clusters for g in finished.get(c.id, [])]
                total = sum(map(len, finished.values()))
            if (trace := current_trace()) and ranked:
                trace.log("gap_finder", "gaps", f"{len(ranked)} in {cluster.id}", phase="partial_result",
                          message=f"Gap finder: {total} gaps so far",
                          payload={"gaps": [{"id": g.id, "cluster_id": g.cluster_id, "paper_ids": g.between_paper_ids,
                                             "description": g.description, "label": g.label} for g in ranked]})
            return ranked

        # Clusters are independent, so each cluster's pipeline runs at the same time (litagent/parallel.py).
        gaps, failure = [], None
        for ranked, error in run_parallel(one, clusters, self.settings.llm_concurrency):
            if error is not None:
                failure = failure or error
            else:
                gaps += ranked
        if failure is not None:
            raise failure
        audit = FindingAudit(stage="gaps", candidate_pairs=len(candidates))
        for gid, outcome in self.outcomes.items():
            accepted = outcome.get("decision") == "accepted"
            audit.decisions.append({"gap_id": gid, **outcome, "decision": outcome.get("decision", "dropped")})
            audit.accepted += accepted
            audit.abstained += outcome.get("abstained", False)
            audit.rejected += not accepted and not outcome.get("abstained", False)
        deps = {g.id: FindingDependency(global_map=False, cluster_ids=[g.cluster_id], paper_ids=g.between_paper_ids)
                for g in gaps}
        return FindingCacheRecord(stage="gaps", created_at=now(), gaps=gaps, dependencies=deps, audit=audit,
                                  full_text=self.fetched)

    # ----- Spec H5: escalate a side cluster to full text -----

    def escalate(self, cluster: Cluster, gaps: list[Gap], candidates: list[dict]) -> list[Gap]:
        """A side cluster that turns out to hold kept gaps is central to them: read full text for its top papers
        (by citations, within a capped budget), log it, and redo that cluster's gaps on the full text."""
        s, ctx = self.settings, self.context
        if (not gaps or getattr(cluster, "kind", None) != "side" or not s.gap_escalation_enabled
                or not ctx.use_full_text or ctx.full_text_ids is None):
            return gaps
        with self.lock:  # the per-run cap holds even when clusters finish at the same time
            if len(self.escalated) >= s.gap_escalation_max_clusters:
                return gaps
            self.escalated.add(cluster.id)
        from litagent.agents.retriever import attach_full_text

        top = sorted((self.by_id[pid] for pid in cluster.paper_ids if not self.by_id[pid].full_text),
                     key=lambda p: (-(p.citation_count or 0), p.id))[:s.gap_escalation_papers]
        got = [p for p in attach_full_text(top, s) if p.full_text]
        if trace := current_trace():
            trace.log("gap_finder", "escalate to full text", f"{len(got)} of {len(top)} papers", phase="partial_result",
                      message=f"Gap finder: side cluster \"{cluster.label}\" holds {len(gaps)} gaps, so its top "
                              f"{len(top)} papers were read in full ({len(got)} PDFs available)",
                      why=f"Spec H5 escalation, capped at {s.gap_escalation_max_clusters} cluster(s) and "
                          f"{s.gap_escalation_papers} papers", payload={"cluster_id": cluster.id,
                                                                       "paper_ids": [p.id for p in got]})
        if not got:
            return gaps
        ids = {p.id for p in got}
        with self.lock:
            for p in got:
                self.by_id[p.id] = p
                self.fetched[p.id] = p.full_text
            ctx.full_text_ids |= ids
            self.source_map.update(sources(got, s, ctx))
        redo = [c for c in candidates if set(c["paper_ids"]) & ids]
        untouched = [g for g in gaps if not set(g.between_paper_ids) & ids]
        kept, _ = self.grade(cluster, self.coverage(self.write(cluster, redo, {})), final=True)
        return self.rank(untouched + kept)

    # ----- Stage 2: gap writer -----

    def write(self, cluster: Cluster, candidates: list[dict], fixes: dict[str, str]) -> list[Gap]:
        if not candidates:
            return []
        drafts, failed = {}, {}

        def ask(chunk: list[dict]) -> list:
            ids = sorted({pid for c in chunk for pid in c["paper_ids"]})
            payload = {"task_version": "gap-writer-v1", "question": self.context.question, "fix": self.fix,
                       "cluster": {"id": cluster.id, "label": cluster.label},
                       "cluster_cards": compact(self.context.cards),
                       "min_quote_chars": self.settings.finding_min_quote_chars,
                       "papers": [self.source_map[pid] for pid in ids],
                       "candidates": [{"gap_id": c["gap_id"], "paper_ids": c["paper_ids"],
                                       **({"fix": fixes[c["gap_id"]], "previous_claim": self.outcomes[c["gap_id"]]["claim"]}
                                          if c["gap_id"] in fixes else {})} for c in chunk]}
            return request("gap_finder", payload, GapDrafts, _no_check, self.settings, self.context, "gaps",
                           retry_timeout=False).drafts

        for chunk in _chunks(candidates, self.settings.gap_llm_batch_size):
            got, lost, error = halve_on_timeout(ask, chunk, "gap writer batch")
            for d in got:
                drafts.setdefault(d.gap_id, d)
            failed.update((c["gap_id"], _failure(error)) for c in lost)
        out = []
        for c in candidates:
            gid, d = c["gap_id"], drafts.get(c["gap_id"])
            if gid in failed:
                self.drop("writer", gid, f"the writer call failed ({failed[gid]}); a later analysis retries it",
                          retry=True, level=logging.WARNING)
                continue
            if d is None:
                self.drop("writer", gid, "the writer returned no draft for this candidate")
                continue
            if d.decision == "abstain":
                self.drop("writer", gid, f"the writer abstained: {d.reason}", abstained=True)
                continue
            self.outcomes[gid].update(claim=d.claim.strip(), abstained=False)
            evidence, problem = self._check_draft(d, c["paper_ids"])
            if problem:
                self.drop("writer", gid, problem, claim=d.claim)
                continue
            a, b = c["paper_ids"]
            out.append(Gap(id=gid, cluster_id=cluster.id, description=d.claim.strip(), between_paper_ids=[a, b],
                why_it_matters=d.warrant.strip(), evidence=evidence, gap_type="inferred", paper_a_id=a, paper_b_id=b,
                warrant=d.warrant.strip(), similarity=c["similarity"], citation_check=c["citation_check"],
                coverage_query=d.coverage_query.strip()))
            self.keep("writer", gid, "claim written; both quotes found in the original text", claim=d.claim)
        return out

    def _check_draft(self, draft, paper_ids: list[str]) -> tuple[list[Evidence], str | None]:
        if not draft.claim.strip() or not draft.warrant.strip():
            return [], "the claim or warrant is empty"
        if not draft.coverage_query.strip() or len(draft.coverage_query) > 240:
            return [], "the coverage query is empty or longer than 240 characters"
        if len(draft.grounds) != 2:
            return [], f"needs exactly one quote from each paper, got {len(draft.grounds)}"
        # The Connection finder's check: each quote is an original span of its own paper, copied by code.
        try:
            evidence = resolve_evidence(draft.grounds, self.source_map, set(paper_ids), self.settings)
        except ValueError as error:
            return [], f"quote check failed: {error}"
        for e in evidence:
            paper = self.by_id[e.paper_id]
            if not any(e.quote in text for text in (paper.abstract, paper.full_text) if text):
                return [], f"quote from {e.paper_id} is not verbatim in its abstract or full text"
        if scope := unsupported_scope_claims([draft.claim, draft.warrant], [self.source_map[pid] for pid in paper_ids]):
            return [], f"the claim asserts {scope}, which neither paper's quoted text states"
        return sorted(evidence, key=lambda e: paper_ids.index(e.paper_id)), None

    # ----- Optional: explicit gaps -----

    def explicit(self, cluster: Cluster) -> list[Gap]:
        papers = [self.by_id[pid] for pid in cluster.paper_ids if self.by_id[pid].abstract]
        if not papers:
            return []
        payload = {"task_version": "gap-explicit-v1", "question": self.context.question,
                   "papers": [{"id": p.id, "title": p.title, "abstract": p.abstract} for p in papers]}
        drafts = request("gap_explicit", payload, ExplicitGapDrafts, _no_check, self.settings, self.context, "gaps").gaps
        return self._explicit_gaps(cluster, [(d.paper_id, d.sentence.strip(), d.coverage_query.strip()) for d in drafts])

    def _explicit_gaps(self, cluster: Cluster, drafts: list[tuple[str, str, str]]) -> list[Gap]:
        out, members = [], set(cluster.paper_ids)
        for pid, sentence, query in drafts:
            gid = "GAPX-" + digest([pid, sentence])[:16]
            if gid in self.outcomes:
                continue
            self.outcomes[gid] = {"pair_id": gid, "paper_ids": [pid], "cluster_ids": [cluster.id],
                                  "scope": "within_cluster", "gap_type": "explicit", "claim": sentence}
            paper = self.by_id.get(pid) if pid in members else None
            if paper is None:
                self.drop("explicit", gid, f"{pid} is not a paper of cluster {cluster.id}")
            elif len(sentence) < self.settings.finding_min_quote_chars or sentence not in (paper.abstract or ""):
                self.drop("explicit", gid, "the sentence is not verbatim in the paper's abstract", sentence=sentence)
            elif not query or len(query) > 240:
                self.drop("explicit", gid, "the coverage query is empty or longer than 240 characters")
            else:
                out.append(Gap(id=gid, cluster_id=cluster.id, description=sentence, between_paper_ids=[pid],
                    why_it_matters="The authors state this as unresolved in their own abstract.",
                    evidence=[Evidence(paper_id=pid, quote=sentence)], gap_type="explicit", paper_a_id=pid,
                    warrant="The authors state this as unresolved in their own abstract.", coverage_query=query))
                self.keep("explicit", gid, "author-stated gap found verbatim in the abstract", sentence=sentence)
        return out

    # ----- Stage 3: coverage search -----

    def coverage(self, gaps: list[Gap]) -> list[Gap]:
        if not gaps:
            return []
        if not self.settings.gap_coverage_check:
            for g in gaps:
                g.coverage_status = "skipped"
                self.keep("coverage", g.id, "coverage search turned off (gap_coverage_check=False)")
            return gaps
        searches, results = {}, {}
        for g in gaps:
            searches[g.id] = self._search(g.coverage_query)
            own = set(g.between_paper_ids) | {_doi(self.by_id[pid].doi) for pid in g.between_paper_ids} - {None}
            seen, top = set(), []
            for paper in (p for s in searches[g.id] for p in s.papers):
                keys = {paper.id, _doi(paper.doi)} - {None}
                if not keys & (own | seen):
                    top.append(paper)
                seen |= keys
            results[g.id] = top[:self.settings.gap_coverage_results]
            self.checked[g.id] = [p.title for p in results[g.id]]
        pool = {p.id: p for g in gaps for p in results[g.id]}
        source_map = sources(list(pool.values()), self.settings, self.context, limit=self.settings.gap_coverage_source_chars)
        verdicts, judge_failures = {}, {}

        def ask(chunk: list[Gap]) -> list:
            shown = {p.id for g in chunk for p in results[g.id]}
            payload = {"task_version": "gap-coverage-v2",
                       "gaps": [{"gap_id": g.id, "claim": g.description, "result_ids": [p.id for p in results[g.id]]}
                                for g in chunk],
                       "papers": [source_map.get(pid) or {"id": pid, "title": p.title, "spans": []}
                                  for pid, p in pool.items() if pid in shown]}
            return request("gap_coverage", payload, CoverageJudgements, _no_check, self.settings, self.context, "gaps",
                           retry_timeout=False, model=self.settings.grader_model).judgements

        for chunk in _chunks([g for g in gaps if results[g.id]], self.settings.gap_llm_batch_size):
            got, lost, error = halve_on_timeout(ask, chunk, "gap coverage batch")
            for j in got:
                verdicts.setdefault(j.gap_id, j)
            judge_failures.update((g.id, _failure(error)) for g in lost)
        out = []
        for g in gaps:
            checks, verdict, ids = searches[g.id], verdicts.get(g.id), [p.id for p in results[g.id]]
            if verdict and verdict.filled:
                filler = verdict.filling_paper_id
                try:
                    if filler not in ids:
                        raise ValueError("the filling paper is not one of this gap's search results")
                    quote = resolve_evidence(verdict.evidence, source_map, {filler}, self.settings)[0].quote
                except ValueError as error:
                    reason = f"the judge said filled but gave no valid quote ({error}); kept as not filled"
                else:
                    self.drop("coverage", g.id, f"already filled by {filler}: {pool[filler].title}",
                              filling_paper_id=filler, filling_title=pool[filler].title, quote=quote, judge=verdict.reason)
                    continue
                status = "not_filled"
            elif not ids:
                all_searches_unavailable = all(s.status == "unavailable" for s in checks)
                status = "unavailable" if all_searches_unavailable else "not_filled"
                reason = "every search failed" if all_searches_unavailable else "the search returned no other papers"
            elif g.id in judge_failures:  # a later analysis retries unavailable coverage
                status, reason = "unavailable", f"the coverage judge call failed ({judge_failures[g.id]})"
            elif verdict is None:
                status, reason = "unavailable", "the coverage judge returned no verdict for this gap"
            else:
                status, reason = "not_filled", verdict.reason
            g.coverage_status = status
            g.coverage = GapCoverage(status="unavailable" if status == "unavailable" else "no_address_found_in_checked_sources",
                checked_at=now(), local_papers_checked=0, searches=checks, reason=reason, scope=COVERAGE_SCOPE)
            self.keep("coverage", g.id, f"{status}: {reason}", query=g.coverage_query, result_ids=ids)
            out.append(g)
        return out

    def _search(self, query: str) -> list[CoverageSearch]:
        providers = [("openalex", search_openalex, OpenAlexError)]
        if os.getenv("SEMANTIC_SCHOLAR_API_KEY"):
            providers.append(("semantic_scholar", search_semantic_scholar, SemanticScholarError))
        checks = []
        for name, search, error_type in providers:
            check_deadline(self.context)
            timeout = min(self.settings.gap_coverage_timeout_s, max(.1, self.context.deadline - time.monotonic()))
            try:
                # Coverage is not restricted by open access, dates or citation counts.
                options = {"request_budget": self.coverage_budget, "settings": self.settings} if name == "openalex" else {}
                if name != "openalex":
                    self.coverage_budget.consume()
                found = search(query, SearchCriteria(topic=self.context.question or query),
                               self.settings.gap_coverage_hits_per_query, open_access_only=False, timeout_s=timeout, attempts=1,
                               **options)
                checks.append(CoverageSearch(query=query, provider=name, checked_at=now(), status="ok", papers=found))
                break  # only fall back when the primary provider fails
            except (error_type, SearchLimitError) as error:
                checks.append(CoverageSearch(query=query, provider=name, checked_at=now(), status="unavailable",
                                             error=mask(str(error))))
        return checks

    # ----- Stage 4: grading agent -----

    def grade(self, cluster: Cluster, gaps: list[Gap], final: bool) -> tuple[list[Gap], dict[str, str]]:
        if not gaps:
            return [], {}
        labels, failed = {}, {}

        def ask(chunk: list[Gap]) -> list:
            payload = {"task_version": "gap-grader-v1", "research_area": self.context.question or cluster.label,
                       "cluster": cluster.label, "cluster_cards": compact(self.context.cards),
                       "gaps": [{"gap_id": g.id, "type": g.gap_type, "claim": g.description, "warrant": g.warrant,
                                 "grounds": [{"paper_id": e.paper_id, "title": self.by_id[e.paper_id].title,
                                              "quote": e.quote} for e in g.evidence],
                                 "coverage": {"status": g.coverage_status, "checked_titles": self.checked.get(g.id, [])}}
                                for g in chunk]}
            return request("gap_grader", payload, GapLabelDecisions, _no_check, self.settings, self.context, "gaps",
                           retry_timeout=False, model=self.settings.grader_model).labels

        for chunk in _chunks(gaps, self.settings.gap_llm_batch_size):
            # Like an unlabelled cluster: a failed call drops only its own gaps, not the run (real run 27 Oct ended
            # partial on one malformed answer). Marked retry, so a later analysis does them again.
            got, lost, error = halve_on_timeout(ask, chunk, "gap grader batch")
            for d in got:
                labels.setdefault(d.gap_id, d)
            failed.update((g.id, _failure(error)) for g in lost)
        kept, fixes = [], {}
        for g in gaps:
            d = labels.get(g.id)
            if g.id in failed:
                self.drop("grading", g.id, f"the grading call failed ({failed[g.id]}); a later analysis retries it",
                          retry=True, level=logging.WARNING)
            elif d is None:
                self.drop("grading", g.id, "the grading agent returned no label")
            elif (d.fix or "").strip():
                if final or g.gap_type == "explicit":
                    self.drop("grading", g.id, f"the claim still misstates its quotes: {d.fix}", label=d.label)
                else:
                    fixes[g.id] = d.fix.strip()
                    _log("grading", g.id, "rewrite", f"fix for the gap writer: {d.fix}", label=d.label)
            elif d.label not in KEPT_LABELS:
                self.drop("grading", g.id, f"labelled {d.label}: {d.reason}", label=d.label)
            else:
                g.label, g.label_reason = d.label, d.reason
                kept.append(g)
        return kept, fixes

    def rank(self, gaps: list[Gap]) -> list[Gap]:
        """Verified gaps first, then novel before known_open, inferred before explicit, then by similarity; capped
        per cluster. A gap is verified when its coverage search ran and found nothing addressing it. Novelty without
        that search is unverified (27 Oct recovery run: 23 of 31 gaps labelled novel, 15 with no completed search),
        so such a gap keeps its label but ranks after every verified gap and is marked unverified."""
        cap = self.settings.gap_max_per_cluster
        ordered = sorted(gaps, key=lambda g: (not novelty_verified(g), KEPT_LABELS.index(g.label),
                                              g.gap_type != "inferred", -(g.similarity or 0), g.id))
        for g in ordered[cap:]:
            self.drop("grading", g.id, f"over the cap of {cap} gaps per cluster", label=g.label)
        for g in ordered[:cap]:
            self.outcomes[g.id]["decision"] = "accepted"
            self.outcomes[g.id]["reason"] = g.label_reason
            note = "" if novelty_verified(g) else f" (novelty unverified: coverage {g.coverage_status})"
            self.keep("grading", g.id, f"labelled {g.label}{note}: {g.label_reason}", label=g.label,
                      novelty_verified=novelty_verified(g))
        return ordered[:cap]

    # ----- trace -----

    def drop(self, stage: str, gap_id: str, reason: str, abstained: bool = False, retry: bool = False,
             level: int = logging.INFO, **result) -> None:
        self.outcomes.setdefault(gap_id, {}).update(decision="abstain" if abstained else "dropped", stage=stage,
                                                    reason=reason, abstained=abstained, **({"retry": True} if retry else {}))
        _log(stage, gap_id, "dropped", reason, level, **result)

    def keep(self, stage: str, gap_id: str, reason: str, **result) -> None:
        _log(stage, gap_id, "kept", reason, **result)


def rewrite_gap(paper_ids: list[str], papers: list[Paper], clusters: list[Cluster], feedback: str,
                previous_claim: str | None, settings: Settings, context: FindingContext) -> list[Gap]:
    """Write one candidate pair's gap again with a human reviewer's feedback, then run its coverage check and the gap
    grader as usual. Used by Submit on the Human review page; an empty list means the gap was dropped."""
    context = prepare(papers, clusters, settings, context)
    source_map = sources(papers, settings, context)
    candidates = candidate_pairs(papers, clusters, context.similarity, settings, set(source_map))
    c = next((c for c in candidates if set(c["paper_ids"]) == set(paper_ids)), None)
    if c is None:
        raise ValueError("This paper pair is no longer a gap candidate on this map")
    run = _Run(papers, source_map, None, settings, context)
    run.outcomes[c["gap_id"]] = {**{k: c[k] for k in ("pair_id", "paper_ids", "cluster_ids", "scope")},
                                 "gap_type": "inferred", "claim": previous_claim or ""}
    cluster = next(cl for cl in clusters if cl.id == c["cluster_id"])
    written = run.write(cluster, [c], {c["gap_id"]: feedback})
    kept, _ = run.grade(cluster, run.coverage(written), final=True)
    return run.rank(kept)


def _sample_gaps(papers: list[Paper], clusters: list[Cluster], settings: Settings) -> list[Gap]:
    """Sample mode: stage 1 runs for real on the stored similarity matrix and reference lists; stages 2-4 are
    labelled placeholders (no LLM, no network), so the output shape and the trace match a real run."""
    similarity = sample_similarity(papers)
    if similarity is None:
        _log("candidates", "-", "dropped", "No stored similarity covers these papers; run scripts/build_sample_gap_inputs.py")
        return []
    run = _Run(papers, {}, None, settings, None)
    candidates = candidate_pairs(papers, clusters, similarity, settings, {p.id for p in papers if first_sentence(p)})
    gaps = []
    for cluster in clusters:
        found = []
        for c in (c for c in candidates if c["cluster_id"] == cluster.id):
            a, b = (run.by_id[pid] for pid in c["paper_ids"])
            run.outcomes[c["gap_id"]] = {**{k: c[k] for k in ("pair_id", "paper_ids", "cluster_ids", "scope")},
                                         "gap_type": "inferred", "claim": "Sample mode placeholder"}
            found.append(Gap(id=c["gap_id"], cluster_id=cluster.id,
                description=f'Sample mode: placeholder gap between "{a.title}" and "{b.title}"; no LLM wrote or checked it.',
                between_paper_ids=c["paper_ids"],
                why_it_matters="Sample mode: illustrates the output shape; no gap or novelty assessment was performed.",
                evidence=[Evidence(paper_id=p.id, quote=first_sentence(p)) for p in (a, b)], gap_type="inferred",
                paper_a_id=a.id, paper_b_id=b.id, warrant="Sample mode: placeholder warrant.",
                similarity=c["similarity"], citation_check=c["citation_check"]))
            run.keep("writer", c["gap_id"], "Sample mode: placeholder claim quoting each abstract's first sentence")
        if settings.gap_explicit_enabled:
            found += run._explicit_gaps(cluster, [(pid, s, "Sample mode") for pid in cluster.paper_ids
                                                  for s in _explicit_sentences(run.by_id[pid].abstract)])
        for g in found:
            g.coverage_status, g.coverage_query = "skipped", None
            g.label, g.label_reason = "known_open", "Sample mode: placeholder label, not assessed."
            run.keep("coverage", g.id, "Sample mode: no network, coverage search skipped")
        gaps += run.rank(found)
    return gaps


def _explicit_sentences(abstract: str | None) -> list[str]:
    """Sample-mode stand-in for the explicit-gap extractor: abstract sentences with a missing-knowledge cue."""
    return [s for s in re.split(r"(?<=[.!?])\s+", abstract or "") if _EXPLICIT_CUE.search(s)]


def _gap_id(a: str, b: str) -> str:
    return "GAP-" + digest([a, b])[:16]


def _doi(doi: str | None) -> str | None:
    return doi.lower().removeprefix("https://doi.org/") if doi else None


def _chunks(items: list, size: int) -> list[list]:
    """Small batches keep each model request well inside the 90 s limit (real run 26 Oct: a 15-candidate writer
    call took 82 s and the next timed out)."""
    return [items[i:i + size] for i in range(0, len(items), size)]


def novelty_verified(gap: Gap) -> bool:
    """The coverage search ran and found no paper addressing the gap; anything else leaves novelty unverified."""
    return gap.coverage_status == "not_filled"


def _failure(error: Exception) -> str:
    return mask(f"{type(error).__name__}: {error}")


def _no_check(output) -> None:
    """Drafts are checked one by one, so one bad item drops only that gap instead of failing the batch."""


def _log(stage: str, gap_id: str, decision: str, reason: str, level: int = logging.INFO, **result) -> None:
    if trace := current_trace():
        trace.log("gap_finder", stage, decision, result=result or None, why=reason, level=level, stage=stage, gap_id=gap_id)
