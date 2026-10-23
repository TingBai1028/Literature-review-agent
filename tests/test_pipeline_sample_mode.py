"""The pipeline runs end to end in sample mode (data/sample/, no network). Keep this passing as you replace stubs."""

import numpy as np

from litagent.agents.clusterer import cosine_similarity_matrix, group_by_threshold
from litagent.agents.grader import check_cluster_sizes
from litagent.config import Effort, Settings
from litagent.human_review import AutoApproveReviewer
from litagent.orchestrator import run_pipeline
from litagent.schemas import Cluster, HumanFeedback


def sample_settings(tmp_path) -> Settings:
    s = Settings()
    s.sample_mode = True
    s.logs_dir = str(tmp_path)
    return s


def test_full_run(tmp_path):
    result = run_pipeline("How do LLMs handle low-resource languages?", Effort.NORMAL, AutoApproveReviewer(), sample_settings(tmp_path))
    assert result.status == "done"
    assert len(result.papers) == 30
    assert result.clusters and result.connections and result.gaps
    assert not result.warnings
    assert (tmp_path / f"trace-{result.run_id}.jsonl").exists()


def test_no_topic_asks_user(tmp_path):
    result = run_pipeline("find papers", Effort.NORMAL, AutoApproveReviewer(), sample_settings(tmp_path))
    assert result.status == "need_topic"
    assert result.message_to_user


def test_defaults_applied(tmp_path):
    result = run_pipeline("graph neural networks for drug discovery", Effort.HIGH, AutoApproveReviewer(), sample_settings(tmp_path))
    assert result.plan.criteria.year_from is not None
    assert result.plan.criteria.paper_types == ["primary", "review"]
    assert result.plan.max_papers == 100


class RejectFirstReviewer(AutoApproveReviewer):
    def __init__(self):
        self.calls = 0

    def review_papers(self, summary):
        self.calls += 1
        if self.calls == 1:
            return HumanFeedback(approved=False, comment="only review papers")
        return HumanFeedback(approved=True)


def test_human_feedback_replans(tmp_path):
    reviewer = RejectFirstReviewer()
    result = run_pipeline("transformers for protein folding", Effort.NORMAL, reviewer, sample_settings(tmp_path))
    assert result.status == "done"
    assert reviewer.calls == 2


def test_group_by_threshold():
    emb = np.array([[1.0, 0.0], [0.99, 0.1], [0.0, 1.0]])
    groups = group_by_threshold(cosine_similarity_matrix(emb), 0.7)
    assert sorted(map(sorted, groups)) == [[0, 1], [2]]


def test_cluster_size_check():
    too_broad = [Cluster(id="C1", label="x", paper_ids=[str(i) for i in range(9)], rationale=""),
                 Cluster(id="C2", label="y", paper_ids=["9"], rationale="")]
    assert check_cluster_sizes(too_broad, 10) is not None


def test_time_limit_returns_partial(tmp_path):
    settings = sample_settings(tmp_path)
    settings.run_timeout_s = 0
    result = run_pipeline("graph neural networks for drug discovery", Effort.NORMAL, AutoApproveReviewer(), settings)
    assert result.status == "partial"
    assert any("time limit" in w for w in result.warnings)


def test_sample_mode_uses_matching_sample_file(tmp_path):
    result = run_pipeline("graph neural networks for drug discovery", Effort.NORMAL, AutoApproveReviewer(), sample_settings(tmp_path))
    assert all(p.source == "openalex" for p in result.papers)
    assert any("drug" in p.title.lower() for p in result.papers)
