"""Bound requests without dropping findings, abstentions, counterevidence or original quotes."""

import json
import threading
from types import SimpleNamespace

import pytest

from litagent.agents import grader
from litagent.config import Settings
from litagent.finding_analysis import grade_stage
from litagent.integrations.llm import LLMError, TokenBudgetExceeded
from litagent.schemas import Evidence, Gap, GapCoverage, Grade, Paper


def corpus(count=31):
    papers = [Paper(id=f"P{i}", title=f"Source {i}", source="test",
                    abstract=f"Source {i} reports controlled experiments and identifies a measurable limitation.")
              for i in range(count + 1)]
    gaps = [Gap(id=f"G{i}", cluster_id="C", description=f"Compare the measured limitations in sources {i} and {i+1}.",
                why_it_matters="Test whether the reported limitation holds under the other protocol.",
                between_paper_ids=[papers[i].id, papers[i+1].id],
                evidence=[Evidence(paper_id=p.id, quote=p.abstract) for p in papers[i:i+2]])
            for i in range(count)]
    pairs = [{"pair_id": f"PAIR{i}", "paper_ids": gap.between_paper_ids} for i, gap in enumerate(gaps)]
    return papers, gaps, pairs


def capture(monkeypatch, scores=None):
    calls = []

    def complete(prompt, message, schema, **kwargs):
        payload = json.loads(message)
        calls.append((message, payload, kwargs))
        points = scores[len(calls)-1] if scores else (3, 3, 2)
        return Grade(stage=payload["stage"], accuracy=points[0], appropriateness=points[1], actionability=points[2],
                     reasoning=f"Checked batch {len(calls)} against original sources.",
                     fix="Recheck G5 against its cited source statements." if sum(points) < 7 else None)

    monkeypatch.setattr(grader, "complete_json", complete)
    return calls


def test_all_31_gaps_and_abstained_pairs_are_graded_with_only_their_sources(monkeypatch):
    papers, gaps, pairs = corpus()
    pairs += [{"pair_id": "ABSTAIN", "paper_ids": ["P0", "P31"], "reason": "Do not pass this to the grader"}]
    original = [g.model_dump_json() for g in gaps]
    calls = capture(monkeypatch)
    settings = Settings(sample_mode=False)
    result = grader.grade("gaps", gaps, papers, settings, reviewed_pairs=pairs, retry_timeout=False)
    outputs = [g for _, p, _ in calls for g in p["output"]]
    reviewed = [pair for _, p, _ in calls for pair in p["reviewed_pairs"]]
    assert [g["id"] for g in outputs] == [g.id for g in gaps]
    assert sorted(p["pair_id"] for p in reviewed) == sorted(p["pair_id"] for p in pairs)
    assert len(calls) == 7 and result.total == 8
    for message, payload, kwargs in calls:
        assert len(message) <= settings.finding_grader_max_input_chars
        assert len(payload["output"]) <= settings.finding_grader_batch_size
        needed = {pid for pair in payload["reviewed_pairs"] for pid in pair["paper_ids"]}
        assert {p["id"] for p in payload["papers"]} == needed
        assert all(set(pair) == {"pair_id", "paper_ids"} for pair in payload["reviewed_pairs"])
        assert kwargs["model"] == settings.grader_model and kwargs["retry_timeout"] is False
    assert original == [g.model_dump_json() for g in gaps]


def test_character_cap_splits_before_sending_without_truncating_quotes(monkeypatch):
    papers, gaps, pairs = corpus(3)
    for gap in gaps:
        gap.description += " Detailed test condition." * 200
    calls = capture(monkeypatch)
    settings = Settings(sample_mode=False, finding_grader_max_input_chars=9500)
    grader.grade("gaps", gaps, papers, settings, reviewed_pairs=pairs)
    assert len(calls) == 3
    for message, payload, _ in calls:
        assert len(message) <= 9500
        item = payload["output"][0]
        original = next(g for g in gaps if g.id == item["id"])
        assert item["description"] == original.description
        assert item["evidence"] == [e.model_dump() for e in original.evidence]


def test_repeated_source_quotes_are_deduplicated_and_coverage_is_compact(monkeypatch):
    papers, gaps, pairs = corpus(2)
    gaps[0].coverage = GapCoverage(status="inconclusive", checked_at="now", local_papers_checked=2,
        evidence=[Evidence(paper_id="EXT", quote="Counterevidence must remain visible to the grader.")],
        addressing_paper_ids=["EXT"], reason="Producer reasoning is not evidence.",
        searches=[{"query": "test", "provider": "openalex", "checked_at": "now", "status": "ok",
                   "papers": [Paper(id="EXT", title="External evidence", abstract="x"*100000,
                                    full_text="y"*100000, references=["REF"]*1000, source="test")]}])
    calls = capture(monkeypatch)
    grader.grade("gaps", gaps, papers, Settings(sample_mode=False), reviewed_pairs=pairs)
    payload = calls[0][1]
    shared = next(p for p in payload["papers"] if p["id"] == "P1")
    assert shared["cited_original_spans"] == [{"field": "abstract", "quote": papers[1].abstract}]
    coverage = payload["output"][0]["coverage"]
    assert coverage["status"] == "inconclusive" and coverage["addressing_paper_ids"] == ["EXT"]
    assert coverage["evidence"] == [e.model_dump() for e in gaps[0].coverage.evidence]
    assert coverage["searches"][0]["papers"] == [{"id": "EXT", "title": "External evidence", "year": None}]
    assert gaps[0].coverage.searches[0].papers[0].full_text == "y"*100000


def test_one_oversized_item_prevents_all_model_calls(monkeypatch):
    papers, gaps, pairs = corpus(7)
    gaps[-1].description += "x"*50000
    calls = capture(monkeypatch)
    with pytest.raises(LLMError, match="exceeds finding_grader_max_input_chars"):
        grader.grade("gaps", gaps, papers, Settings(sample_mode=False), reviewed_pairs=pairs)
    assert calls == []


def test_empty_scope_cannot_bypass_character_cap(monkeypatch):
    calls = capture(monkeypatch)
    with pytest.raises(LLMError, match="exceeds finding_grader_max_input_chars"):
        grader.grade("gaps", [], [], Settings(sample_mode=False), question="x"*50000, reviewed_pairs=[])
    assert calls == []


def test_failed_batch_is_not_averaged_into_a_passing_stage(monkeypatch):
    papers, gaps, pairs = corpus(6)
    capture(monkeypatch, [(3, 3, 3), (1, 2, 1)])
    # One at a time, so the scores follow batch order
    result = grader.grade("gaps", gaps, papers, Settings(sample_mode=False, llm_concurrency=1), reviewed_pairs=pairs)
    assert result.total == 4 and result.fix == "Recheck G5 against its cited source statements."
    assert "Batch 1: 9/9" in result.reasoning and "Batch 2: 4/9" in result.reasoning


def test_empty_output_preserves_all_reviewed_abstentions(monkeypatch):
    papers, _, pairs = corpus(12)
    calls = capture(monkeypatch)
    grader.grade("gaps", [], papers, Settings(sample_mode=False), reviewed_pairs=pairs)
    assert len(calls) == 3
    assert sum(len(p["reviewed_pairs"]) for _, p, _ in calls) == 12
    assert all("abstention is justified" in p["empty_output"] for _, p, _ in calls)


def test_batch_failure_keeps_findings_and_leaves_the_stage_ungraded(monkeypatch):
    papers, gaps, pairs = corpus(6)
    calls = capture(monkeypatch)
    complete = grader.complete_json

    def fail_second(*args, **kwargs):
        if calls:
            raise LLMError("Provider unavailable")
        return complete(*args, **kwargs)

    monkeypatch.setattr(grader, "complete_json", fail_second)
    result = SimpleNamespace(analysis=SimpleNamespace(pending_stages=[], grades={}), warnings=[])
    world = SimpleNamespace(record_grade=lambda *args: pytest.fail("Incomplete batches must not produce a grade"))
    grade_stage(result, "gaps", gaps, papers, Settings(sample_mode=False, llm_concurrency=1), world, {"reviewed_pairs": pairs})
    assert result.analysis.pending_stages == ["gaps_grade"] and result.analysis.grades == {}
    assert len(gaps) == 6 and "grade unavailable" in result.warnings[0]


def test_expired_deadline_stops_before_the_next_batch(monkeypatch):
    papers, gaps, pairs = corpus(6)
    calls = capture(monkeypatch)
    times = iter([1, 3])
    monkeypatch.setattr(grader.time, "monotonic", lambda: next(times))
    with pytest.raises(TokenBudgetExceeded, match="grading time limit"):
        grader.grade("gaps", gaps, papers, Settings(sample_mode=False, llm_concurrency=1), reviewed_pairs=pairs, deadline=2)
    assert len(calls) == 1


def test_batches_are_graded_at_the_same_time(monkeypatch):
    # 27 Oct: 11 gap batches one after another (~60 s each on the checking model) ran past the time limit.
    papers, gaps, pairs = corpus(10)
    calls = capture(monkeypatch)
    complete = grader.complete_json
    both_waiting = threading.Barrier(2, timeout=5)

    def concurrent(*args, **kwargs):
        both_waiting.wait()  # raises BrokenBarrierError if the second batch only starts after the first returns
        return complete(*args, **kwargs)

    monkeypatch.setattr(grader, "complete_json", concurrent)
    result = grader.grade("gaps", gaps, papers, Settings(sample_mode=False, llm_concurrency=2), reviewed_pairs=pairs)
    assert len(calls) == 2 and result.total == 8
