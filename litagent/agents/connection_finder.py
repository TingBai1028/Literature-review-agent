"""4. Connection finder agent. Spec: docs/agents/connection_finder.md

Finds paper-to-paper edges within each cluster first, then between clusters (never cluster-to-cluster).
Every edge carries a relation type, a short and a long reason a human can read, evidence notes and
Evidence (paper id + verbatim quote). A critic rejects generic reasons; each is regenerated once.
"""

from __future__ import annotations

from collections import defaultdict

from litagent.config import Settings
from litagent.finding_engine import (FindingContext, cached, cache_key, choose_pairs, exact_ids, merge_record, now,
    pair_payload, prepare, request, resolve_evidence, sources, verify)
from litagent.schemas import (DIRECTIONAL_RELATIONS, Cluster, Connection, ConnectionDecisions, Evidence, FindingAudit,
                             FindingCacheRecord, FindingDependency, GroundedConnection, Paper)
from litagent.trace import current_trace


def find_connections(papers: list[Paper], clusters: list[Cluster], settings: Settings, fix: str | None = None,
                     *, context: FindingContext | None = None) -> list[Connection]:
    if settings.sample_mode:
        return _fake_connections(papers, clusters)

    context = prepare(papers, clusters, settings, context)
    source_map = sources(papers, settings, context)
    pairs, skipped = choose_pairs("connections", papers, clusters, settings, context, set(source_map))
    report = FindingAudit(stage="connections", candidate_pairs=len(pairs), duplicate_pairs_skipped=skipped)
    groups = defaultdict(list)
    for pair in pairs:
        groups[tuple(pair["cluster_ids"])].append(pair)
    out = []
    context.partial_connections = []
    try:
        for group in groups.values():
            payload = {"task_version": "connections-v2", "question": context.question, "fix": fix,
                       "min_quote_chars": settings.finding_min_quote_chars,
                       "pairs": [pair_payload(p, source_map, clusters) for p in group]}
            key = cache_key("connections", payload, ConnectionDecisions, settings)
            record = cached(key, context, settings)
            reused = record is not None
            if record is None:
                record = _assess(group, payload, source_map, papers, settings, context)
                context.cache[key] = record
            merge_record(report, record, context, reused=reused)
            out.extend(c.model_copy(deep=True) for c in record.connections)
            context.partial_connections = list(out)
        return out
    finally:
        context.audits.append(report)


def _assess(pairs, payload, source_map, papers, settings, context):
    targets = {p["pair_id"]: p for p in pairs}
    references = {p.id: p.references for p in papers}
    evidence = {}

    def validate_for(expected):
        def validate(output):
            exact_ids([d.pair_id for d in output.decisions], expected, "pair_id")
            for d in output.decisions:
                if d.decision != "supported":
                    continue
                pair = targets[d.pair_id]
                if not d.relation or not d.reason_short.strip() or not d.reason_long.strip():
                    raise ValueError(f"{d.pair_id}: a supported edge needs a relation, reason_short and reason_long")
                if d.relation in DIRECTIONAL_RELATIONS and d.base_paper_id not in pair["paper_ids"]:
                    raise ValueError(f"{d.pair_id}: {d.relation} needs base_paper_id, one of {pair['paper_ids']}")
                if d.relation == "directly_cites":
                    if pair["cited"] and d.base_paper_id != pair["cited"]:
                        raise ValueError(f"{d.pair_id}: the reference lists say {pair['citation']}; base_paper_id is the cited paper")
                    if not pair["cited"] and all(references[pid] is not None for pid in pair["paper_ids"]):
                        raise ValueError(f"{d.pair_id}: the reference lists show no citation between these papers; "
                                         "choose another relation or abstain")
                evidence[d.pair_id] = resolve_evidence(d.evidence, source_map, set(pair["paper_ids"]), settings)
        return validate

    def claims(decisions):
        return [{"pair_id": d.pair_id, "relation": d.relation, "reason_short": d.reason_short, "reason_long": d.reason_long,
                 "evidence_notes": d.evidence_notes, "citation": targets[d.pair_id]["citation"],
                 "evidence": [e.model_dump() for e in evidence[d.pair_id]],
                 "papers": [source_map[pid] for pid in targets[d.pair_id]["paper_ids"]]}
                for d in decisions if d.decision == "supported"]

    output = request("connection_finder", payload, ConnectionDecisions, validate_for(targets), settings, context, "connections")
    decisions = {d.pair_id: d for d in output.decisions}
    checked = verify(claims(decisions.values()), settings, context, "connections")
    generic = sorted(pid for pid, v in checked.items() if v.verdict == "generic")
    if generic:
        # Spec D4: the critic rejected these reasons as generic; regenerate each once with its feedback.
        if trace := current_trace():
            trace.log("connection_finder", "critic: generic reasons", f"rewrite {len(generic)} edge(s) once",
                      result={pid: checked[pid].reason for pid in generic}, next_step="regenerate",
                      why="A reason must name something concrete in both papers", step_kind="llm")
        retry_payload = {**payload, "pairs": [p for p in payload["pairs"] if p["pair_id"] in generic],
                         "fix": "The critic rejected these reasons as generic: "
                                + "; ".join(f"{pid}: {checked[pid].reason}" for pid in generic)
                                + ". Name the concrete method, dataset, claim or citation that both quotes show, or abstain."}
        retried = request("connection_finder", retry_payload, ConnectionDecisions, validate_for(set(generic)),
                          settings, context, "connections").decisions
        for d in retried:
            decisions[d.pair_id] = d
            checked.pop(d.pair_id, None)
        checked.update(verify(claims(retried), settings, context, "connections"))
    connections, deps = [], {}
    audit = FindingAudit(stage="connections", candidate_pairs=len(pairs))
    for pid, d in decisions.items():
        verdict = checked.get(pid)
        accepted = d.decision == "supported" and verdict.verdict == "supported"
        audit.decisions.append({"pair_id": pid, "paper_ids": targets[pid]["paper_ids"], "rewritten": pid in generic,
                               "decision": "accepted" if accepted else "abstain" if verdict is None else "rejected",
                               "reason": verdict.reason if verdict else d.reason})
        if not accepted:
            if verdict is None:
                audit.abstained += 1
            else:
                audit.rejected += 1
            continue
        pair = targets[pid]
        a, b = pair["paper_ids"]
        source, target = (d.base_paper_id, b if d.base_paper_id == a else a) if d.relation in DIRECTIONAL_RELATIONS else (a, b)
        notes = [n.strip() for n in d.evidence_notes if n.strip()][:5]
        if pair["citation"] and not any(pair["citation"] in n for n in notes):
            notes.append(pair["citation"])  # from the reference lists, so it is a fact rather than a model claim
        cid = "CONN-" + pid.removeprefix("PAIR-")
        connections.append(GroundedConnection(id=cid, kind=pair["kind"], paper_ids=[source, target],
            cluster_ids=pair["cluster_ids"], description=d.reason_short.strip(), reason_short=d.reason_short.strip(),
            reason_long=d.reason_long.strip(), evidence_notes=notes, relation=d.relation, similarity=pair["similarity"],
            evidence=sorted(evidence[pid], key=lambda e: [source, target].index(e.paper_id))))
        deps[cid] = FindingDependency(global_map=False, cluster_ids=pair["cluster_ids"], paper_ids=pair["paper_ids"])
        audit.accepted += 1
    return FindingCacheRecord(stage="connections", created_at=now(), connections=connections, dependencies=deps, audit=audit)


def _fake_connections(papers: list[Paper], clusters: list[Cluster]) -> list[Connection]:
    """Sample mode (no LLM): one placeholder edge per cluster between its first two papers with an abstract, plus an
    edge for every citation between sample papers, taken from their stored OpenAlex reference lists."""
    by_id = {p.id: p for p in papers}
    owner = {pid: c.id for c in clusters for pid in c.paper_ids}
    out, linked = [], set()
    for citing in papers:
        for cited in (ref for ref in citing.references or () if ref in by_id and ref in owner and by_id[ref].abstract):
            if not citing.abstract or citing.id not in owner:
                continue
            note = f"{citing.id} cites {cited}"
            out.append(Connection(id=f"CITE-{citing.id}-{cited}", paper_ids=[cited, citing.id],
                kind="within_cluster" if owner[cited] == owner[citing.id] else "between_clusters",
                cluster_ids=sorted({owner[cited], owner[citing.id]}), description=f"Sample mode: {note} (OpenAlex reference list).",
                reason_short=f"Sample mode: {note} (OpenAlex reference list).",
                reason_long="Sample mode: the citation comes from the stored OpenAlex reference list; no model read the papers "
                            "to say how one builds on the other.", evidence_notes=[note],
                evidence=[Evidence(paper_id=p.id, quote=first_sentence(p)) for p in (by_id[cited], citing)]))
            linked.add(frozenset((cited, citing.id)))
    for c in clusters:
        quotable = [pid for pid in c.paper_ids if pid in by_id and by_id[pid].abstract]
        if len(quotable) >= 2 and frozenset(quotable[:2]) not in linked:
            a, b = quotable[:2]
            text = "Sample mode: placeholder link between two papers of the same cluster; no reason was assessed."
            out.append(Connection(id=f"{c.id}-K1", kind="within_cluster", paper_ids=[a, b], cluster_ids=[c.id],
                description=text, reason_short=text, reason_long=text,
                evidence=[Evidence(paper_id=a, quote=first_sentence(by_id.get(a))),
                          Evidence(paper_id=b, quote=first_sentence(by_id.get(b)))]))
    return out


def first_sentence(paper: Paper | None, limit: int = 200) -> str:
    """A verbatim snippet from the abstract, used as sample-mode evidence."""
    if paper is None or not paper.abstract:
        return ""
    text = paper.abstract
    end = text.find(". ")
    return text[: end + 1 if 0 < end < limit else limit]
