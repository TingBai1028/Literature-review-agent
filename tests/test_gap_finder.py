"""Gap finder stages (docs/agents/gap_finder.md), with the LLM and the literature search mocked."""

import json

import numpy as np
import pytest

from litagent import finding_engine as engine
from litagent.agents import gap_finder
from litagent.config import Effort, Settings
from litagent.finding_engine import FindingContext
from litagent.human_review import AutoApproveReviewer
from litagent.orchestrator import run_pipeline
from litagent.schemas import (Cluster, CoverageJudgement, CoverageJudgements, EvidenceReference, ExplicitGapDraft,
    ExplicitGapDrafts, GapDraft, GapDrafts, GapLabelDecision, GapLabelDecisions, Paper)
from litagent.trace import Trace

IDS = ["A", "B", "C", "D"]


def paper(pid, references=None, extra=""):
    return Paper(id=pid, title=f"Study {pid}", source="openalex", references=references,
                 abstract=f"Study {pid} reports a controlled experiment on task {pid} with measured outcomes.{extra}")


def matrix(pairs: dict[tuple[str, str], float], ids=IDS) -> np.ndarray:
    m = np.eye(len(ids))
    for (a, b), value in pairs.items():
        m[ids.index(a), ids.index(b)] = m[ids.index(b), ids.index(a)] = value
    return m


class FakeLLM:
    """Writes a gap for every candidate; tests switch individual behaviours on."""

    def __init__(self):
        self.calls, self.fabricate, self.fix_first, self.labels = [], set(), set(), {}
        self.filled_by = None
        self.explicit = []

    def __call__(self, prompt, message, schema, **kwargs):
        data = json.loads(message)
        self.calls.append((schema, data))
        if schema is GapDrafts:
            spans = {p["id"]: p["spans"][0]["span_id"] for p in data["papers"]}
            return GapDrafts(drafts=[GapDraft(gap_id=c["gap_id"], decision="write",
                claim=f"Paper {c['paper_ids'][0]} shows X. Paper {c['paper_ids'][1]} shows Y. No work combines them.",
                grounds=[EvidenceReference(paper_id=pid, span_id="S99" if pid in self.fabricate else spans[pid])
                         for pid in c["paper_ids"]],
                warrant="Each paper supplies one half of the combination.", coverage_query="combine X and Y",
                reason="Grounded in both papers.") for c in data["candidates"]])
        if schema is CoverageJudgements:
            return CoverageJudgements(judgements=[CoverageJudgement(gap_id=g["gap_id"], filled=self.filled_by in g["result_ids"],
                filling_paper_id=self.filled_by if self.filled_by in g["result_ids"] else None, reason="Checked results.",
                evidence=[EvidenceReference(paper_id=self.filled_by, span_id="S1")] if self.filled_by in g["result_ids"] else [])
                for g in data["gaps"]])
        if schema is GapLabelDecisions:
            out = []
            for g in data["gaps"]:
                fix = "Say only what the quote of the first paper states." if g["gap_id"] in self.fix_first else None
                self.fix_first.discard(g["gap_id"])
                out.append(GapLabelDecision(gap_id=g["gap_id"], label=self.labels.get(g["gap_id"], "novel"),
                                            reason="One-sentence reason.", fix=fix))
            return GapLabelDecisions(labels=out)
        if schema is ExplicitGapDrafts:
            return ExplicitGapDrafts(gaps=self.explicit)
        raise AssertionError(schema)

    def writer_pairs(self):
        return [c["paper_ids"] for schema, data in self.calls if schema is GapDrafts for c in data["candidates"]]


@pytest.fixture
def llm(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(engine, "complete_json", fake)
    monkeypatch.setattr(engine, "embed_documents", lambda *a, **k: pytest.fail("use the supplied similarity matrix"))
    return fake


@pytest.fixture
def search(monkeypatch):
    state = {"hits": [], "queries": []}
    def fake(query, criteria, limit, open_access_only, **kwargs):
        state["queries"].append(query)
        return state["hits"]
    monkeypatch.setattr(gap_finder, "search_openalex", fake)
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    return state


def run(papers, sims, tmp_path, settings=None):
    settings = settings or Settings(sample_mode=False, logs_dir=str(tmp_path))
    clusters = [Cluster(id="C1", label="Topic", rationale="", paper_ids=[p.id for p in papers])]
    with Trace(str(tmp_path)) as trace:
        gaps = gap_finder.find_gaps(papers, clusters, [], settings, context=FindingContext(similarity=sims))
    return gaps, trace.events


def lines(events, stage, decision=None):
    return [e for e in events if e.get("stage") == stage and e.get("gap_id") and (decision is None or e["decision"] == decision)]


def test_pair_outside_similarity_range_is_never_sent_to_the_llm(llm, search, tmp_path):
    papers = [paper(pid) for pid in IDS]
    sims = matrix({("A", "B"): .95, ("A", "C"): .3, ("B", "C"): .7, ("A", "D"): .2, ("B", "D"): .1, ("C", "D"): .85})
    gaps, events = run(papers, sims, tmp_path)
    assert llm.writer_pairs() == [["B", "C"]] and [g.between_paper_ids for g in gaps] == [["B", "C"]]
    assert all(("B", "C") != tuple(e["result"]["paper_ids"]) for e in lines(events, "candidates", "dropped"))
    assert sum("outside 0.5-0.8" in e["why"] for e in lines(events, "candidates", "dropped")) == 5
    llm.calls.clear()
    assert run(papers, matrix({("B", "C"): .9}), tmp_path)[0] == [] and llm.calls == []


def test_pair_that_cites_each_other_is_dropped_in_stage_1(tmp_path):
    papers = [paper("A", references=["B", "W-elsewhere"]), paper("B", references=[]), paper("C", references=["A", "D"]),
              paper("D", references=["W-elsewhere"])]
    sims = matrix({pair: .7 for pair in [("A", "B"), ("A", "C"), ("A", "D"), ("B", "C"), ("B", "D"), ("C", "D")]})
    clusters = [Cluster(id="C1", label="Topic", rationale="", paper_ids=IDS)]
    with Trace(str(tmp_path)) as trace:
        kept = gap_finder.candidate_pairs(papers, clusters, sims, Settings(sample_mode=False))
    reasons = {tuple(e["result"]["paper_ids"]): e["why"] for e in lines(trace.events, "candidates", "dropped")}
    assert reasons[("A", "B")] == "one paper cites the other"
    assert reasons[("A", "C")] == "one paper cites the other"
    assert reasons[("A", "D")] == "retrieved paper C already cites both"
    assert reasons[("C", "D")] == "one paper cites the other"
    assert {tuple(c["paper_ids"]): c["citation_check"] for c in kept} == {("B", "C"): "passed", ("B", "D"): "passed"}
    papers[1] = paper("B", references=None)  # no reference list -> kept, but the citation check is unknown
    kept = gap_finder.candidate_pairs(papers, clusters, sims, Settings(sample_mode=False))
    assert {tuple(c["paper_ids"]): c["citation_check"] for c in kept}[("B", "C")] == "unknown"


def test_candidates_are_capped_per_cluster_before_any_llm_call(llm, search, tmp_path):
    ids = [f"P{i}" for i in range(8)]
    papers = [paper(pid) for pid in ids]
    sims = np.full((8, 8), .7) - np.arange(64).reshape(8, 8) / 1000
    sims = (sims + sims.T) / 2
    np.fill_diagonal(sims, 1)
    settings = Settings(sample_mode=False, logs_dir=str(tmp_path), gap_max_per_cluster=2, gap_candidate_multiplier=3)
    gaps, events = run(papers, sims, tmp_path, settings)
    assert len(llm.writer_pairs()) == 6 and len(gaps) == 2
    sent = sorted((sims[ids.index(a), ids.index(b)] for a, b in llm.writer_pairs()), reverse=True)
    assert sent[-1] >= max(sims[i, j] for i in range(8) for j in range(i + 1, 8)
                           if sorted([ids[i], ids[j]]) not in llm.writer_pairs())
    assert sum("over the cap of 6" in e["why"] for e in lines(events, "candidates", "dropped")) == 28 - 6


def test_fabricated_quote_is_dropped_in_stage_2(llm, search, tmp_path):
    papers = [paper(pid) for pid in IDS]
    llm.fabricate = {"C"}  # the writer cites a span that paper C does not have
    gaps, events = run(papers, matrix({("A", "B"): .7, ("A", "C"): .75}), tmp_path)
    assert [g.between_paper_ids for g in gaps] == [["A", "B"]]
    dropped = lines(events, "writer", "dropped")
    assert len(dropped) == 1 and "quote check failed" in dropped[0]["why"]
    assert search["queries"] == ["combine X and Y"]  # the dropped gap never reached the coverage search
    by_id = {p.id: p for p in papers}
    assert all(e.quote in by_id[e.paper_id].abstract for e in gaps[0].evidence)


def test_gap_filled_by_a_search_result_is_dropped_in_stage_3(llm, search, tmp_path):
    papers = [paper(pid) for pid in IDS]
    filler = Paper(id="W-FILL", title="Combining X and Y", source="openalex",
                   abstract="We combine the controlled experiments of both tasks and report measured outcomes.")
    search["hits"] = [papers[0], filler]  # paper A itself is excluded from the results the judge sees
    llm.filled_by = "W-FILL"
    gaps, events = run(papers, matrix({("A", "B"): .7}), tmp_path)
    assert gaps == []
    judged = next(data for schema, data in llm.calls if schema is CoverageJudgements)
    assert judged["gaps"][0]["result_ids"] == ["W-FILL"]
    dropped = lines(events, "coverage", "dropped")[0]
    assert dropped["result"]["filling_paper_id"] == "W-FILL" and "Combining X and Y" in dropped["why"]
    assert not any(schema is GapLabelDecisions for schema, _ in llm.calls)


@pytest.mark.parametrize("label,kept", [("trivial", False), ("known_solved", False), ("known_open", True), ("novel", True)])
def test_trivial_and_known_solved_labels_are_dropped_in_stage_4(llm, search, tmp_path, label, kept):
    papers = [paper(pid) for pid in IDS]
    llm.labels = {gap_finder._gap_id("A", "B"): label}
    gaps, events = run(papers, matrix({("A", "B"): .7}), tmp_path)
    assert bool(gaps) is kept
    if kept:
        assert gaps[0].label == label and gaps[0].label_reason and gaps[0].coverage_status == "not_filled"
    else:
        assert f"labelled {label}" in lines(events, "grading", "dropped")[0]["why"]


def test_survivors_rank_novel_first_then_by_similarity_and_are_capped(llm, search, tmp_path):
    papers = [paper(pid) for pid in IDS]
    llm.labels = {gap_finder._gap_id("A", "B"): "known_open", gap_finder._gap_id("C", "D"): "known_open"}
    settings = Settings(sample_mode=False, logs_dir=str(tmp_path), gap_max_per_cluster=2)
    gaps, events = run(papers, matrix({("A", "B"): .79, ("A", "C"): .6, ("C", "D"): .7}), tmp_path, settings)
    assert [(g.between_paper_ids, g.label) for g in gaps] == [(["A", "C"], "novel"), (["A", "B"], "known_open")]
    assert "over the cap of 2" in lines(events, "grading", "dropped")[0]["why"]


def test_grading_fix_rewrites_the_gap_once(llm, search, tmp_path):
    papers = [paper(pid) for pid in IDS]
    gid = gap_finder._gap_id("A", "B")
    llm.fix_first = {gid}
    gaps, events = run(papers, matrix({("A", "B"): .7}), tmp_path)
    rewrites = [data["candidates"][0] for schema, data in llm.calls if schema is GapDrafts and "fix" in data["candidates"][0]]
    assert len(rewrites) == 1 and rewrites[0]["fix"].startswith("Say only") and rewrites[0]["previous_claim"]
    assert [g.id for g in gaps] == [gid] and lines(events, "grading", "rewrite")


def test_explicit_gaps_skip_stages_1_and_2_and_need_verbatim_sentences(llm, search, tmp_path):
    stated = " Whether this holds in field conditions remains unknown."
    papers = [paper("A", extra=stated), paper("B")]
    llm.explicit = [ExplicitGapDraft(paper_id="A", sentence=stated.strip(), coverage_query="field conditions task A"),
                    ExplicitGapDraft(paper_id="B", sentence="Study B leaves scaling open.", coverage_query="scaling task B")]
    settings = Settings(sample_mode=False, logs_dir=str(tmp_path), gap_explicit_enabled=True)
    gaps, events = run(papers, matrix({("A", "B"): .95}, ["A", "B"]), tmp_path, settings)
    assert llm.writer_pairs() == []
    assert [(g.gap_type, g.between_paper_ids, g.evidence[0].quote) for g in gaps] == [("explicit", ["A"], stated.strip())]
    assert "not verbatim" in lines(events, "explicit", "dropped")[0]["why"]


def test_sample_mode_runs_end_to_end_and_produces_gaps(tmp_path):
    settings = Settings(sample_mode=True, logs_dir=str(tmp_path))
    result = run_pipeline("How do LLMs handle low-resource languages?", Effort.NORMAL, AutoApproveReviewer(), settings)
    assert result.status == "done" and result.gaps and result.usage.llm_calls == 0
    by_id = {p.id: p for p in result.papers}
    for g in result.gaps:
        assert g.gap_type == "inferred" and settings.gap_similarity_min <= g.similarity <= settings.gap_similarity_max
        assert g.label == "known_open" and g.coverage_status == "skipped" and g.citation_check in {"passed", "unknown"}
        assert all(e.quote in by_id[e.paper_id].abstract for e in g.evidence)
    assert max(sum(g.cluster_id == c.id for g in result.gaps) for c in result.clusters) <= settings.gap_max_per_cluster
    events = [json.loads(line) for line in (tmp_path / f"trace-{result.run_id}.jsonl").read_text().splitlines()]
    assert {e.get("stage") for e in events if e["agent_name"] == "gap_finder"} >= {"candidates", "writer", "coverage", "grading"}


def test_model_requests_go_in_small_batches(llm, search, tmp_path):
    ids = [f"P{i}" for i in range(5)]
    papers = [paper(pid) for pid in ids]
    sims = np.full((5, 5), .7)
    np.fill_diagonal(sims, 1)
    settings = Settings(sample_mode=False, logs_dir=str(tmp_path), gap_llm_batch_size=3)
    gaps, _ = run(papers, sims, tmp_path, settings)
    writer = [d["candidates"] for schema, d in llm.calls if schema is GapDrafts]
    grader = [d["gaps"] for schema, d in llm.calls if schema is GapLabelDecisions]
    assert sum(map(len, writer)) == 10 and max(map(len, writer)) == 3  # 10 candidate pairs in 4 requests
    assert max(map(len, grader)) <= 3 and gaps


def test_a_failure_in_a_later_cluster_keeps_the_finished_clusters_gaps(llm, search, tmp_path, monkeypatch):
    from litagent.integrations.llm import TokenBudgetExceeded as LLMError  # only time or budget still stops the stage
    original = llm.__call__
    def fail_second_cluster(prompt, message, schema, **kwargs):
        if schema is GapDrafts and json.loads(message)["cluster"]["id"] == "C2":
            raise LLMError("Finding analysis time limit reached")
        return original(prompt, message, schema, **kwargs)
    monkeypatch.setattr(engine, "complete_json", fail_second_cluster)
    papers = [paper(pid) for pid in IDS]
    clusters = [Cluster(id="C1", label="One", rationale="", paper_ids=["A", "B"]),
                Cluster(id="C2", label="Two", rationale="", paper_ids=["C", "D"])]
    context = FindingContext(similarity=matrix({("A", "B"): .7, ("C", "D"): .7}))
    with pytest.raises(LLMError):
        gap_finder.find_gaps(papers, clusters, [], Settings(sample_mode=False, logs_dir=str(tmp_path)), context=context)
    assert [g.between_paper_ids for g in context.partial_gaps] == [["A", "B"]]


def test_a_failed_grading_call_drops_only_its_gaps_and_is_retried_later(llm, search, tmp_path, monkeypatch):
    from litagent.integrations.llm import LLMError
    original, failed = llm.__call__, []
    def fail_first_grading(prompt, message, schema, **kwargs):
        if schema is GapLabelDecisions and not failed:
            failed.append(json.loads(message)["gaps"][0]["gap_id"])
            raise LLMError("GapLabelDecisions: model output failed validation twice")
        return original(prompt, message, schema, **kwargs)
    monkeypatch.setattr(engine, "complete_json", fail_first_grading)
    papers = [paper(pid) for pid in IDS]
    settings = Settings(sample_mode=False, logs_dir=str(tmp_path), gap_llm_batch_size=1)
    context = FindingContext(similarity=matrix({("A", "B"): .7, ("C", "D"): .7}))
    clusters = [Cluster(id="C1", label="Topic", rationale="", paper_ids=IDS)]
    with Trace(str(tmp_path)) as trace:
        gaps = gap_finder.find_gaps(papers, clusters, [], settings, context=context)
    assert len(gaps) == 1 and gaps[0].id != failed[0]
    [dropped] = lines(trace.events, "grading", "dropped")
    assert dropped["gap_id"] == failed[0] and "a later analysis retries it" in dropped["why"]
    graded = sum(schema is GapLabelDecisions for schema, _ in llm.calls)
    again = gap_finder.find_gaps(papers, clusters, [], settings, context=context)  # not reused from the cache
    assert len(again) == 2 and sum(schema is GapLabelDecisions for schema, _ in llm.calls) == graded + 2


def _timeout():
    import httpx
    from openai import APITimeoutError
    return APITimeoutError(request=httpx.Request("POST", "http://nightshift.test/v1/chat/completions"))


def test_a_timed_out_writer_batch_is_asked_again_in_halves(llm, search, tmp_path, monkeypatch):
    original, sizes = llm.__call__, []
    def slow_when_big(prompt, message, schema, **kwargs):
        assert kwargs.get("retry_timeout") is False  # the halves are the retry
        if schema is GapDrafts:
            sizes.append(len(json.loads(message)["candidates"]))
            if sizes[-1] > 1:
                raise _timeout()
        return original(prompt, message, schema, **kwargs)
    monkeypatch.setattr(engine, "complete_json", slow_when_big)
    papers = [paper(pid) for pid in IDS]
    gaps, events = run(papers, matrix({("A", "B"): .7, ("C", "D"): .7}), tmp_path)
    assert sizes == [2, 1, 1] and len(gaps) == 2


def test_a_failed_writer_or_coverage_call_drops_or_defers_only_its_gaps(llm, search, tmp_path, monkeypatch):
    from litagent.integrations.llm import LLMError
    original = llm.__call__
    def fail(prompt, message, schema, **kwargs):
        data = json.loads(message)
        if schema is GapDrafts and data["candidates"][0]["paper_ids"] == ["A", "B"]:
            raise LLMError("GapDrafts: model output failed validation twice")
        if schema is CoverageJudgements:
            raise _timeout()
        return original(prompt, message, schema, **kwargs)
    monkeypatch.setattr(engine, "complete_json", fail)
    search["hits"] = [paper("EXT")]
    papers = [paper(pid) for pid in IDS]
    settings = Settings(sample_mode=False, logs_dir=str(tmp_path), gap_llm_batch_size=1)
    gaps, events = run(papers, matrix({("A", "B"): .7, ("C", "D"): .7}), tmp_path, settings)
    [dropped] = lines(events, "writer", "dropped")
    assert dropped["gap_id"] == gap_finder._gap_id("A", "B") and "a later analysis retries it" in dropped["why"]
    assert [g.between_paper_ids for g in gaps] == [["C", "D"]]
    assert gaps[0].coverage_status == "unavailable" and "coverage judge call failed" in gaps[0].coverage.reason


def test_the_stage_grader_gets_coverage_hits_as_titles_not_full_records(monkeypatch):
    from litagent.agents import grader
    from litagent.schemas import CoverageSearch, Evidence, Gap, GapCoverage
    a, b, hit = paper("A"), paper("B"), paper("EXT", references=[f"W{i}" for i in range(50)])
    gap = Gap(id="g1", cluster_id="C1", description="A shows X. B shows Y.", between_paper_ids=["A", "B"],
              why_it_matters="w", evidence=[Evidence(paper_id=p.id, quote=p.abstract) for p in (a, b)],
              coverage=GapCoverage(status="no_address_found_in_checked_sources", checked_at="t", local_papers_checked=0,
                                   reason="r", searches=[CoverageSearch(query="q", checked_at="t", status="ok", papers=[hit])]))
    sent = {}
    def capture(prompt, message, model, **kwargs):
        sent.update(json.loads(message), retry_timeout=kwargs.get("retry_timeout"))
        return model(stage="gaps", reasoning="ok", accuracy=3, appropriateness=3, actionability=3)
    monkeypatch.setattr(grader, "complete_json", capture)
    grader.grade("gaps", [gap], [a, b], Settings(sample_mode=False), reviewed_pairs=[], retry_timeout=False)
    [search] = sent["output"][0]["coverage"]["searches"]
    assert search["papers"] == [{"id": "EXT", "title": "Study EXT", "year": None}] and sent["retry_timeout"] is False
