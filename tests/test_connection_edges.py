"""Paper-to-paper edges with readable reasons (spec D), with the LLM mocked."""

import json
import tempfile

import numpy as np
import pytest

from litagent import finding_engine as engine
from litagent.agents import connection_finder
from litagent.config import Effort, Settings
from litagent.finding_engine import FindingContext
from litagent.human_review import AutoApproveReviewer
from litagent.integrations.llm import LLMError
from litagent.orchestrator import run_pipeline
from litagent.schemas import (Cluster, ConnectionDecision, ConnectionDecisions, EvidenceReference, FindingVerification,
    FindingVerifications, GroundedConnection, Paper)
from litagent.trace import Trace


def paper(pid, references=None):
    return Paper(id=pid, title=f"Study {pid}", source="openalex", references=references,
                 abstract=f"Study {pid} trains a contrastive encoder on chest X-ray images and reports measured accuracy.")


class FakeLLM:
    def __init__(self, relation="same_method_different_domain", base=None):
        self.calls, self.relation, self.base = [], relation, base
        self.verdicts = []  # verdicts for successive verifier calls; "supported" once exhausted

    def __call__(self, prompt, message, schema, **kwargs):
        data = json.loads(message)
        self.calls.append((schema, data))
        if schema is ConnectionDecisions:
            return ConnectionDecisions(decisions=[ConnectionDecision(pair_id=p["pair_id"], decision="supported",
                relation=self.relation, base_paper_id=self.base,
                reason_short="Both papers train a contrastive encoder on chest X-ray images.",
                reason_long="Each paper trains a contrastive encoder on chest X-rays and reports accuracy.",
                evidence_notes=["shared method: contrastive encoder"], reason="Quotes show the shared method.",
                evidence=[EvidenceReference(paper_id=x["id"], span_id=x["spans"][0]["span_id"]) for x in p["papers"]])
                for p in data["pairs"]])
        if schema is FindingVerifications:
            verdict = self.verdicts.pop(0) if self.verdicts else "supported"
            return FindingVerifications(verdicts=[FindingVerification(pair_id=c["pair_id"], verdict=verdict,
                reason="Name the shared encoder and dataset." if verdict == "generic" else "Checked.") for c in data["claims"]])
        raise AssertionError(schema)


@pytest.fixture
def llm(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(engine, "complete_json", fake)
    return fake


def run(papers, sims, clusters=None):
    clusters = clusters or [Cluster(id="C1", label="Topic", rationale="", paper_ids=[p.id for p in papers])]
    with Trace(tempfile.mkdtemp()) as trace:
        found = connection_finder.find_connections(papers, clusters, Settings(sample_mode=False),
                                                   context=FindingContext(similarity=sims))
    return found, trace.events


def test_every_edge_links_two_papers_and_carries_readable_reasons(llm):
    ps = [paper("A"), paper("B"), paper("C")]
    clusters = [Cluster(id="C1", label="One", rationale="", paper_ids=["A", "B"]),
                Cluster(id="C2", label="Two", rationale="", paper_ids=["C"])]
    sims = np.array([[1, .8, .7], [.8, 1, .6], [.7, .6, 1]])
    found, _ = run(ps, sims, clusters)
    assert found and all(isinstance(c, GroundedConnection) for c in found)
    paper_ids = {p.id for p in ps}
    for edge in found:
        assert set(edge.paper_ids) <= paper_ids and len(edge.paper_ids) == 2  # never a cluster id
        assert edge.reason_short and edge.reason_long and edge.evidence_notes and edge.description == edge.reason_short
    assert {c.kind for c in found} == {"within_cluster", "between_clusters"}


def test_generic_reason_is_regenerated_once_then_kept_if_concrete(llm):
    llm.verdicts = ["generic", "supported"]
    found, events = run([paper("A"), paper("B")], np.array([[1, .8], [.8, 1]]))
    rewrites = [d for schema, d in llm.calls if schema is ConnectionDecisions and "generic" in (d.get("fix") or "")]
    assert len(rewrites) == 1 and "Name the shared encoder" in rewrites[0]["fix"]
    assert len(found) == 1 and any(e["action"] == "critic: generic reasons" for e in events)


def test_still_generic_after_one_rewrite_is_dropped(llm):
    llm.verdicts = ["generic", "generic"]
    found, _ = run([paper("A"), paper("B")], np.array([[1, .8], [.8, 1]]))
    assert found == [] and sum(schema is ConnectionDecisions for schema, _ in llm.calls) == 2


def test_citation_pairs_are_candidates_below_the_similarity_floor_and_point_to_the_cited_paper(monkeypatch):
    fake = FakeLLM(relation="directly_cites", base="A")
    monkeypatch.setattr(engine, "complete_json", fake)
    found, _ = run([paper("A", references=[]), paper("B", references=["A"])], np.array([[1, .2], [.2, 1]]))
    sent = next(d for schema, d in fake.calls if schema is ConnectionDecisions)["pairs"][0]
    assert sent["citation"] == "B cites A"
    assert found[0].paper_ids == ["A", "B"] and found[0].relation == "directly_cites"
    assert "B cites A" in found[0].evidence_notes  # added by code from the reference lists


def test_directly_cites_contradicting_known_reference_lists_is_rejected(monkeypatch):
    fake = FakeLLM(relation="directly_cites", base="A")
    monkeypatch.setattr(engine, "complete_json", fake)
    with pytest.raises(LLMError, match="bounded source validation"):
        run([paper("A", references=[]), paper("B", references=[])], np.array([[1, .8], [.8, 1]]))
    repaired = [d for schema, d in fake.calls if schema is ConnectionDecisions and "validation_error" in d]
    assert repaired and "no citation" in repaired[0]["validation_error"]


def test_sample_mode_edges_all_have_reasons_and_citations_come_from_reference_lists(tmp_path):
    result = run_pipeline("protein structure prediction with transformers", Effort.NORMAL, AutoApproveReviewer(),
                          Settings(sample_mode=True, logs_dir=str(tmp_path)))
    assert result.connections and all(c.reason_short and c.reason_long for c in result.connections)
    by_id = {p.id: p for p in result.papers}
    cites = [c for c in result.connections if c.evidence_notes]
    assert cites and all(c.paper_ids[0] in (by_id[c.paper_ids[1]].references or []) for c in cites)
