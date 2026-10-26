"""Full-PDF vs metadata analysis per cluster and cluster cards (spec H)."""

import json

import numpy as np
import pytest

from litagent import cluster_cards, finding_engine as engine
from litagent.agents import gap_finder, retriever
from litagent.cluster_cards import build_cards, full_text_ids, read_role_full_text
from litagent.config import Settings
from litagent.finding_engine import FindingContext, sources
from litagent.integrations.llm import LLMError
from litagent.schemas import (ClusterCardSummaries, ClusterCardSummary, Paper, PaperClusterDetail, QuestionCluster)
from litagent.trace import Trace
from tests.test_gap_finder import FakeLLM, matrix, paper
from tests.test_question_clusters import models  # noqa: F401  (offline model fixture)


def cluster(cid, kind, ids, keywords=()):
    return QuestionCluster(id=cid, kind=kind, label=f"{kind} topic", rationale="Why these papers belong together.",
        question="Q", paper_ids=ids, role_reason="reason",
        paper_details=[PaperClusterDetail(paper_id=pid, question_similarity=.5, relevance="uncertain", reason="r",
                                          keywords=list(keywords)) for pid in ids])


def oa(pid, year=2020, cites=10):
    return Paper(id=pid, title=f"Study {pid}", abstract=f"Study {pid} reports a controlled experiment.", year=year,
                 citation_count=cites, is_open_access=True, pdf_url=f"https://x/{pid}.pdf", source="openalex")


ROLES = [cluster("MAIN", "main", ["A", "B"], ["adapters"]), cluster("FOUNDATION", "foundation", ["C"]),
         cluster("SIDE-1", "side", ["D", "E"], ["speech", "speech"])]


def test_full_text_is_read_for_main_and_foundation_papers_only(monkeypatch, tmp_path):
    fetched = []
    monkeypatch.setattr(retriever, "fetch_full_text", lambda url, **k: fetched.append(url) or f"Body of {url}. " * 5)
    papers = [oa(p) for p in "ABCDE"]
    with Trace(str(tmp_path)) as trace:
        out = read_role_full_text(papers, ROLES, Settings(sample_mode=False))
    assert sorted(fetched) == ["https://x/A.pdf", "https://x/B.pdf", "https://x/C.pdf"]
    assert [bool(p.full_text) for p in out] == [True, True, True, False, False]
    assert any("side papers analysed from metadata" in e["message"] for e in trace.events)


def test_cards_hold_role_numbers_keywords_and_one_batched_summary(monkeypatch):
    calls = []
    def summarise(prompt, message, schema, **kwargs):
        calls.append(json.loads(message))
        assert schema is ClusterCardSummaries
        return ClusterCardSummaries(cards=[ClusterCardSummary(cluster_id=c["cluster_id"], summary=f"About {c['label']}.")
                                           for c in calls[-1]["clusters"]])
    monkeypatch.setattr(cluster_cards, "complete_json", summarise)
    papers = [oa("A", 2001, 900), oa("B", 2010, 30), oa("C", 1995, 5000), oa("D", 2022, 3), oa("E", 2023, 1)]
    papers[0] = papers[0].model_copy(update={"full_text": "Adapters keep 98% of accuracy. " * 20})
    cards = build_cards(papers, ROLES, "How do adapters work?", Settings(sample_mode=False))
    main, foundation, side = cards
    assert len(calls) == 1 and [c["analysis_depth"] for c in calls[0]["clusters"]] == ["full_pdf", "full_pdf", "metadata"]
    assert "Adapters keep" in calls[0]["clusters"][0]["papers"][0]["text"]  # full-text passage for main
    assert calls[0]["clusters"][2]["papers"][0]["text"].startswith("Study")  # abstract for side
    assert main.year_range == (2001, 2010) and main.citations == {"median": 465.0, "max": 900.0}
    assert side.keywords == ["speech"] and side.analysis_depth == "metadata" and foundation.role == "foundation"
    assert main.summary == "About main topic." and main.papers_with_full_text == 1


def test_cards_fall_back_to_label_and_rationale_when_the_summary_call_fails(monkeypatch):
    monkeypatch.setattr(cluster_cards, "complete_json", lambda *a, **k: (_ for _ in ()).throw(LLMError("down")))
    cards = build_cards([oa(p) for p in "ABCDE"], ROLES, "Q", Settings(sample_mode=False))
    assert cards[0].summary == "main topic. Why these papers belong together."


def test_side_papers_are_analysed_from_metadata_even_with_full_text_on_record():
    papers = [oa("A").model_copy(update={"full_text": "Main body passage about the method. " * 10}),
              oa("D").model_copy(update={"full_text": "Side body passage that must not be read. " * 10})]
    context = FindingContext(use_full_text=True, full_text_ids=full_text_ids(ROLES))
    out = sources(papers, Settings(sample_mode=False), context)
    assert out["A"]["source_field"] == "full_text" and out["D"]["source_field"] == "abstract"


@pytest.fixture
def llm(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(engine, "complete_json", fake)
    monkeypatch.setattr(gap_finder, "search_openalex", lambda *a, **k: [])
    return fake


def run_gaps(papers, clusters, settings, use_full_text, ids):
    context = FindingContext(similarity=matrix({("A", "B"): .7}, [p.id for p in papers]), use_full_text=use_full_text,
                             full_text_ids=set(ids), cards=build_cards(papers, clusters, "Q", settings))
    with Trace(settings.logs_dir) as trace:
        gaps = gap_finder.find_gaps(papers, clusters, [], settings, context=context)
    return gaps, trace.events


def test_gap_writer_and_grader_read_the_cluster_cards(llm, tmp_path):
    papers = [paper("A"), paper("B")]
    clusters = [cluster("MAIN", "main", ["A", "B"])]
    run_gaps(papers, clusters, Settings(sample_mode=False, logs_dir=str(tmp_path)), False, ["A", "B"])
    payloads = [d for schema, d in llm.calls if schema.__name__ in {"GapDrafts", "GapLabelDecisions"}]
    assert payloads and all(d["cluster_cards"][0]["cluster_id"] == "MAIN" for d in payloads)


def test_a_side_cluster_holding_gaps_is_escalated_to_full_text_once(llm, monkeypatch, tmp_path):
    fetched = []
    body = "Study {} reports a controlled experiment on task {} with measured outcomes in full detail. "
    monkeypatch.setattr(retriever, "fetch_full_text",
                        lambda url, **k: fetched.append(url) or body.format(url[9], url[9]) * 8)
    papers = [paper(pid).model_copy(update={"is_open_access": True, "pdf_url": f"https://x/{pid}.pdf",
                                            "citation_count": 10 - i}) for i, pid in enumerate("AB")]
    clusters = [cluster("SIDE-1", "side", ["A", "B"])]
    settings = Settings(sample_mode=False, logs_dir=str(tmp_path))
    gaps, events = run_gaps(papers, clusters, settings, True, [])
    assert sorted(fetched) == ["https://x/A.pdf", "https://x/B.pdf"]
    assert any(e["action"] == "escalate to full text" and "read in full" in e["message"] for e in events)
    assert gaps and all(p.full_text for p in papers)  # the caller's papers carry the fetched text for grading
    assert all(any(e.quote in (p.full_text or "") or e.quote in (p.abstract or "") for p in papers) for g in gaps
               for e in g.evidence)
    fetched.clear()
    run_gaps([paper("A"), paper("B")], clusters, settings, False, [])  # metadata modes never escalate
    assert fetched == []


def test_a_full_text_map_downloads_main_and_foundation_pdfs_only_and_saves_cards(models, monkeypatch, tmp_path):
    from litagent.cluster_preview import run_cluster_map
    from litagent.cluster_state import load_version
    from litagent.config import Effort
    from tests.test_question_clusters import ROLES as SMALL_ROLES
    ps, _ = models
    ps = [p.model_copy(update={"is_open_access": True, "pdf_url": f"https://x/{p.id}.pdf"}) for p in ps]
    fetched = []
    monkeypatch.setattr(retriever, "fetch_full_text", lambda url, **k: fetched.append(url) or "Full body text. " * 200)
    cfg = Settings(sample_mode=False, logs_dir=str(tmp_path), **SMALL_ROLES)
    result = run_cluster_map(ps, "First question", Effort.HIGH, cfg, "cards-map")
    deep = full_text_ids(result.clusters)
    assert fetched and sorted(fetched) == sorted(f"https://x/{pid}.pdf" for pid in deep)
    assert [c.analysis_depth for c in result.cluster_cards] == ["full_pdf" if c.kind != "side" else "metadata"
                                                                for c in result.clusters]
    saved, state, _ = load_version("cards-map", cfg)
    assert saved.cluster_cards == result.cluster_cards
    assert {p.id for p in state.papers if p.full_text} <= deep
