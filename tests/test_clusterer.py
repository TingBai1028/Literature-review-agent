"""Clusterer (real, non-sample path) with embeddings and the LLM mocked."""

import json

import numpy as np
import pytest

from litagent.agents import clusterer
from litagent.agents.clusterer import ClusterLabel, ClusterLabels, adjust_threshold, average_linkage, cluster
from litagent.config import Effort, Settings
from litagent.human_review import AutoApproveReviewer
from litagent.orchestrator import run_pipeline
from litagent.schemas import Cluster, Paper
from litagent.trace import Trace


def unit(deg: float) -> list[float]:
    return [np.cos(np.radians(deg)), np.sin(np.radians(deg))]


# Two tight groups (around 0 and 90 degrees) and one outlier at 45 degrees (cosine 0.71 to both)
ANGLES = {"P1": 0, "P2": 4, "P3": 88, "P4": 90, "P5": 93, "P6": 45}
PAPERS = [Paper(id=pid, title=f"Title {pid}", abstract=f"Abstract {pid}.", source="openalex") for pid in ANGLES]


def real_settings(threshold=0.85) -> Settings:
    s = Settings()
    s.sample_mode = False
    s.cluster_similarity_threshold = threshold
    s.cluster_threshold_step = 0.03
    return s


@pytest.fixture
def fakes(monkeypatch):
    """Fake embeddings from ANGLES and a fake labeller; returns the messages sent to the LLM."""
    sent = []
    monkeypatch.setattr(clusterer, "embed", lambda texts: np.array([unit(ANGLES[t.split(".")[0].split()[-1]]) for t in texts]))

    def fake_llm(system_prompt, user_message, output_model, **kwargs):
        message = json.loads(user_message)
        sent.append(message)
        return ClusterLabels(labels=[ClusterLabel(cluster_id=c["cluster_id"], label=f"Label {c['cluster_id']}",
                                                  rationale="r") for c in message["clusters"]])

    monkeypatch.setattr(clusterer, "complete_json", fake_llm)
    return sent


# ----- grouping -----

def test_average_linkage_does_not_chain():
    # A~B and B~C are close but A and C are far apart: connected components would make one group
    sim = np.array([[1.0, 0.9, 0.1], [0.9, 1.0, 0.9], [0.1, 0.9, 1.0]])
    assert average_linkage(sim, 0.8) == [[0, 1], [2]]


def test_average_linkage_extremes():
    sim = np.full((4, 4), 0.95)
    assert average_linkage(sim, 0.9) == [[0, 1, 2, 3]]
    assert average_linkage(np.eye(4), 0.5) == [[0], [1], [2], [3]]


@pytest.mark.parametrize("fix, expected", [
    ("One cluster is too broad; split the largest cluster.", 0.88),
    ("Too many single-paper clusters; lower the similarity threshold or merge.", 0.82),
    ("No clusters were produced.", 0.82),
    ("Make the labels more specific.", 0.85),
    (None, 0.85),
])
def test_grader_fix_moves_the_threshold(fix, expected):
    assert adjust_threshold(0.85, fix, 0.03) == pytest.approx(expected)


# ----- cluster() -----

def test_groups_are_labelled_and_the_outlier_is_left_out(fakes):
    clusters = cluster(PAPERS, Effort.NORMAL, real_settings())
    assert [(c.id, c.paper_ids) for c in clusters] == [("C1", ["P3", "P4", "P5"]), ("C2", ["P1", "P2"])]
    assert [c.label for c in clusters] == ["Label C1", "Label C2"]
    assert "P6" not in {pid for c in clusters for pid in c.paper_ids}
    assert len(fakes) == 1  # one LLM call labels every group
    assert fakes[0]["clusters"][1]["papers"][0] == {"title": "Title P1", "abstract_start": "Abstract P1."}


def test_grader_fix_reaches_the_labeller_and_the_log(fakes, tmp_path):
    with Trace(str(tmp_path)) as trace:
        cluster(PAPERS, Effort.NORMAL, real_settings(), fix="One cluster is too broad; split the largest cluster.")
    assert fakes[0]["fix_from_grader"].startswith("One cluster is too broad")
    grouped = next(e for e in trace.events if e["action"] == "group papers")
    assert "0.88" in grouped["why"] and "threshold moved" in grouped["why"]


def test_incoherent_group_is_dropped_and_ids_renumbered(fakes, monkeypatch):
    def llm(system_prompt, user_message, output_model, **kwargs):
        return ClusterLabels(labels=[
            ClusterLabel(cluster_id="C1", label="Mixed", rationale="no shared idea", coherent=False),
            ClusterLabel(cluster_id="C2", label="Pair", rationale="r"),
        ])

    monkeypatch.setattr(clusterer, "complete_json", llm)
    clusters = cluster(PAPERS, Effort.NORMAL, real_settings())
    assert [(c.id, c.label, c.paper_ids) for c in clusters] == [("C1", "Pair", ["P1", "P2"])]


def test_group_the_labeller_skipped_gets_a_fallback_label(fakes, monkeypatch):
    monkeypatch.setattr(clusterer, "complete_json",
                        lambda *a, **k: ClusterLabels(labels=[ClusterLabel(cluster_id="C1", label="Big", rationale="r")]))
    clusters = cluster(PAPERS, Effort.NORMAL, real_settings())
    assert [c.label for c in clusters] == ["Big", "Title P1"]


def test_too_few_papers_or_no_groups(fakes):
    assert cluster(PAPERS[:1], Effort.NORMAL, real_settings()) == []
    assert cluster(PAPERS, Effort.NORMAL, real_settings(threshold=0.9999)) == []
    assert fakes == []  # no LLM call when there is nothing to label


# ----- orchestrator -----

def test_orchestrator_records_unclustered_papers(tmp_path, monkeypatch):
    monkeypatch.setattr(clusterer, "cluster", lambda papers, effort, settings, fix=None: [
        Cluster(id="C1", label="A", paper_ids=[p.id for p in papers[:12]], rationale="r"),
        Cluster(id="C2", label="B", paper_ids=[p.id for p in papers[12:24]], rationale="r"),
        Cluster(id="C3", label="C", paper_ids=[p.id for p in papers[24:28]], rationale="r"),
    ])
    settings = Settings()
    settings.sample_mode = True
    settings.logs_dir = str(tmp_path)
    result = run_pipeline("graph neural networks for drug discovery", Effort.NORMAL, AutoApproveReviewer(), settings)
    expected = [p.id for p in result.papers[28:]]
    assert len(expected) == 2 and result.unclustered_paper_ids == expected
    assert result.paper_map["unclustered"] == sorted(expected)


def test_docker_image_bakes_the_configured_embedding_model():
    from pathlib import Path

    from litagent.config import EMBEDDING_MODEL

    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text()
    assert f"ARG EMBEDDING_MODEL={EMBEDDING_MODEL}" in dockerfile
