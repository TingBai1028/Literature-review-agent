"""Independent model calls run at the same time (litagent/parallel.py) without changing any result."""

import json
import threading
import time

import numpy as np
import pytest

from litagent import cluster_labels, finding_engine as engine, question_clusters
from litagent.agents import clusterer, connection_finder, gap_finder
from litagent.config import Effort, Settings
from litagent.finding_engine import FindingContext
from litagent.integrations.llm import TokenMeter, current_meter
from litagent.parallel import parallel_map, run_parallel
from litagent.schemas import (Cluster, ConnectionDecision, ConnectionDecisions, EvidenceReference, FindingVerification,
                              FindingVerifications)
from litagent.trace import Trace, current_trace
from tests.test_gap_finder import FakeLLM, paper
from tests.test_question_clusters import ROLES, models  # noqa: F401  (offline clustering fixture)


class Overlap:
    """Wraps a fake model: every call waits a little and records how many calls were in flight at once."""

    def __init__(self, inner, delay=.05):
        self.inner, self.delay, self.lock = inner, delay, threading.Lock()
        self.now = self.peak = 0

    def __call__(self, *args, **kwargs):
        with self.lock:
            self.now += 1
            self.peak = max(self.peak, self.now)
        try:
            time.sleep(self.delay)
            return self.inner(*args, **kwargs)
        finally:
            with self.lock:
                self.now -= 1


def test_parallel_map_keeps_order_runs_at_once_and_raises_after_all_finish():
    started = time.monotonic()
    assert parallel_map(lambda x: (time.sleep(.2), x * 2)[1], [1, 2, 3, 4], 4) == [2, 4, 6, 8]
    assert time.monotonic() - started < .6
    ran = []
    def flaky(x):
        ran.append(x)
        if x in (2, 3):
            raise ValueError(f"bad {x}")
        return x
    with pytest.raises(ValueError, match="bad 2"):
        parallel_map(flaky, [1, 2, 3, 4], 4)
    assert sorted(ran) == [1, 2, 3, 4]
    assert [e is None for _, e in run_parallel(flaky, [1, 2, 4], 2)] == [True, False, True]


def test_tasks_log_to_the_runs_trace_and_count_against_its_budget(tmp_path):
    with Trace(str(tmp_path), "threads") as trace, TokenMeter(10_000) as meter:
        def work(i):
            current_trace().log("clusterer", f"step {i}", "done", payload={"i": i})
            current_meter().add(10, 5)
            return i
        parallel_map(work, list(range(200)), 8)
    lines = (tmp_path / "trace-threads.jsonl").read_text().splitlines()
    assert len(lines) == 200 and sorted(json.loads(line)["payload"]["i"] for line in lines) == list(range(200))
    assert meter.usage.llm_calls == 200 and meter.usage.total == 3000 and len(trace.events) == 200


class Model(FakeLLM):
    """The gap finder's fake model, which also supports every connection pair and its source check."""

    def __call__(self, prompt, message, schema, **kwargs):
        data = json.loads(message)
        if schema is ConnectionDecisions:
            return ConnectionDecisions(decisions=[ConnectionDecision(pair_id=p["pair_id"], decision="supported",
                relation="same_problem_different_method", reason_short="Both papers run controlled experiments.",
                reason_long="Each paper reports measurements from controlled experiments on its task.",
                evidence_notes=["same task: controlled experiments"], reason="The spans state the task.",
                evidence=[EvidenceReference(paper_id=x["id"], span_id=x["spans"][0]["span_id"]) for x in p["papers"]])
                for p in data["pairs"]])
        if schema is FindingVerifications:
            return FindingVerifications(verdicts=[FindingVerification(pair_id=c["pair_id"], verdict="supported",
                reason="Independent source check.") for c in data["claims"]])
        return super().__call__(prompt, message, schema, **kwargs)


def timeless(value):
    """A result without the moment its coverage was checked, which differs between any two runs."""
    if isinstance(value, dict):
        return {k: timeless(v) for k, v in value.items() if k != "checked_at"}
    return [timeless(v) for v in value] if isinstance(value, list) else value


def corpus(n_clusters):
    ids = [f"{chr(65 + c)}{i}" for c in range(n_clusters) for i in range(3)]
    papers = [paper(pid) for pid in ids]
    sims = np.full((len(ids), len(ids)), .3)
    for c in range(n_clusters):
        sims[3 * c:3 * c + 3, 3 * c:3 * c + 3] = .7
    np.fill_diagonal(sims, 1)
    clusters = [Cluster(id=f"C{c}", label=f"Topic {c}", rationale="", paper_ids=ids[3 * c:3 * c + 3])
                for c in range(n_clusters)]
    return papers, sims, clusters


@pytest.mark.parametrize("finder", ["gaps", "connections"])
def test_finders_give_the_same_result_in_parallel_as_one_after_another(monkeypatch, tmp_path, finder):
    papers, sims, clusters = corpus(4)
    monkeypatch.setattr(gap_finder, "search_openalex", lambda *a, **k: [])
    results, peaks = {}, {}
    for workers in (1, 4):
        fake = Overlap(Model())
        monkeypatch.setattr(engine, "complete_json", fake)
        settings = Settings(sample_mode=False, logs_dir=str(tmp_path), llm_concurrency=workers,
                            connection_max_within_pairs=8, connection_within_pairs_per_cluster=2)
        context = FindingContext(similarity=sims)
        run = gap_finder.find_gaps if finder == "gaps" else connection_finder.find_connections
        args = (papers, clusters, [], settings) if finder == "gaps" else (papers, clusters, settings)
        results[workers] = timeless([x.model_dump() for x in run(*args, context=context)])
        peaks[workers] = fake.peak
    assert results[4] == results[1] and results[1]
    assert peaks[1] == 1 and peaks[4] > 1


def test_clustering_gives_the_same_map_in_parallel(models, monkeypatch):
    ps, _ = models
    maps = {}
    for workers in (1, 4):
        settings = Settings(sample_mode=False, llm_concurrency=workers, main_relevance_batch_size=1,
                            cluster_label_batch_size=1, **ROLES)
        relevance = Overlap(question_clusters.complete_json)
        labels = Overlap(cluster_labels.complete_json)
        monkeypatch.setattr(question_clusters, "complete_json", relevance)
        monkeypatch.setattr(cluster_labels, "complete_json", labels)
        maps[workers] = [c.model_dump() for c in clusterer.cluster(ps, Effort.NORMAL, settings, question="First question")]
        monkeypatch.setattr(question_clusters, "complete_json", relevance.inner)
        monkeypatch.setattr(cluster_labels, "complete_json", labels.inner)
        if workers == 4:
            assert relevance.peak > 1
    assert maps[4] == maps[1]
