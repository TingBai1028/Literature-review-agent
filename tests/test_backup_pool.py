"""Fast/Pro modes, citation ranking, backup pool and refresh (spec F)."""

import json

import pytest
from fastapi.testclient import TestClient

from litagent import api
from litagent.agents import planner, retriever
from litagent.cluster_preview import run_cluster_map
from litagent.cluster_state import VersionError, head, load_version
from litagent.config import EFFORT_PROFILES, Effort, Settings
from litagent.refresh import refresh_map
from litagent.schemas import Connection, Evidence, Paper, SearchCriteria, SearchPlan
from litagent.trace import Trace

QUESTION = "How do LLMs handle low-resource languages?"


def paper(pid, cites=0, refs=None):
    return Paper(id=pid, title=f"Paper {pid}", abstract="An abstract.", citation_count=cites, reference_count=refs,
                 source="openalex")


def plan(effort=Effort.FAST, queries=("q1", "q2", "q3")):
    profile = EFFORT_PROFILES[effort]
    return SearchPlan(question=QUESTION, criteria=SearchCriteria(topic=QUESTION), queries=list(queries), effort=effort,
                      max_papers=profile.max_papers, token_budget=profile.token_budget,
                      retrieval_target=profile.retrieval_target)


def test_modes_sit_between_the_old_levels():
    fast, pro = EFFORT_PROFILES[Effort.FAST], EFFORT_PROFILES[Effort.PRO]
    assert fast.retrieval_target == 300 and pro.retrieval_target == 1000 and fast.max_papers == pro.max_papers == 50
    assert EFFORT_PROFILES[Effort.NORMAL].token_budget <= fast.token_budget <= pro.token_budget <= EFFORT_PROFILES[Effort.ULTRA].token_budget


def test_citations_lift_a_slightly_less_relevant_paper_to_the_top():
    ranked = retriever.pool_rank([(paper("relevant", cites=0), .9), (paper("classic", cites=5000), .8),
                                  (paper("neither", cites=10), .5)], .7)
    assert [p.id for p in ranked] == ["classic", "relevant", "neither"]


def test_zero_reference_papers_go_to_the_backup_pool_only(tmp_path):
    scored = [(paper(f"P{i}", cites=100 - i, refs=0 if i < 3 else 20), 1 - i / 100) for i in range(60)]
    with Trace(str(tmp_path)) as trace:
        shown, backup = retriever.split_pool(scored, plan(), Settings(sample_mode=False), 600, 60, "floor applied")
    assert len(shown) == 50 and all(p.reference_count for p in shown)
    assert [p.id for p in backup][:3] == ["P0", "P1", "P2"] and len(backup) == 10
    note = next(e for e in trace.events if e["action"] == "rank pool")
    assert "short of the 300 target" in note["why"] and "3 with no references" in note["why"]
    assert note["payload"] == {"retrieved": 60, "target": 300, "shown": 50, "backup": 10}


def test_fast_spreads_its_retrieval_target_over_the_searches(monkeypatch):
    limits = []
    def search(query, criteria, limit, open_access_only):
        limits.append(limit)
        return [paper(f"{query}-{i}", refs=5) for i in range(3)]
    monkeypatch.setattr(retriever, "search_openalex", search)
    monkeypatch.setattr(retriever, "apply_relevance_floor", lambda kept, q, s: (kept, "floor skipped"))
    shown, backup = retriever.retrieve_pool(plan(), Settings(sample_mode=False, retrieval_sources=("openalex",)))
    assert limits == [100, 100, 100] and len(shown) == 9 and backup == []


def test_search_returns_the_pool_and_the_map_stores_it(tmp_path):
    cfg = Settings(sample_mode=True, logs_dir=str(tmp_path))
    api.app.dependency_overrides[api.get_settings] = lambda: cfg
    try:
        with TestClient(api.app) as client:
            found = client.post("/search", json={"input": {"query": QUESTION}}).json()["output"]
            assert found["plan"]["effort"] == "fast" and len(found["papers"]) == 50 and found["backup_papers"]
            body = {"run_id": "pool-map", "input": {"query": QUESTION, "papers": found["papers"],
                                                    "backup_papers": found["backup_papers"]}}
            built = client.post("/cluster", json=body).json()["output"]
            dup = {"input": {"query": QUESTION, "papers": found["papers"][:2], "backup_papers": found["papers"][:1]}}
            assert client.post("/cluster", json=dup).status_code == 422
    finally:
        api.app.dependency_overrides.clear()
    assert built["backup_pool_size"] == len(found["backup_papers"])
    assert [p.id for p in load_version("pool-map", cfg)[1].backup_papers] == [p["id"] for p in found["backup_papers"]]


@pytest.fixture
def fast_map(tmp_path):
    cfg = Settings(sample_mode=True, logs_dir=str(tmp_path))
    p = planner.plan(QUESTION, Effort.FAST, cfg).plan
    shown, backup = retriever.retrieve_pool(p, cfg)
    return run_cluster_map(shown, QUESTION, Effort.FAST, cfg, "fast-map", backup_papers=backup), cfg, backup


def test_refresh_swaps_side_papers_and_keeps_main_and_foundation(fast_map):
    source, cfg, backup = fast_map
    child = refresh_map("fast-map", source.version_token, cfg, "fast-map-2")
    fixed = lambda m: [(c.id, c.label, c.paper_ids) for c in m.clusters if c.kind != "side"]
    assert fixed(child) == fixed(source)
    shown = lambda m: {pid for c in m.clusters for pid in c.paper_ids}
    assert len(shown(child)) == len(shown(source))  # the map keeps its size
    assert child.refresh["swapped_in"] == [p.id for p in backup[:len(child.refresh["swapped_in"])]]
    assert set(child.refresh["swapped_in"]) <= shown(child) and not set(child.refresh["swapped_out"]) & shown(child)
    pool = [p.id for p in load_version(child.run_id, cfg)[1].backup_papers]
    assert pool[-len(child.refresh["swapped_out"]):] == child.refresh["swapped_out"]  # swapped-out papers return to the pool
    assert head(source.root_run_id, cfg)["run_id"] == child.run_id and child.parent_run_id == "fast-map"


def test_refresh_drops_findings_on_swapped_papers_and_marks_stages_pending(fast_map, tmp_path):
    source, cfg, _ = fast_map
    # Refresh swaps the least question-relevant side papers first, so this one always leaves the map.
    leaving = min((d for c in source.clusters if c.kind == "side" for d in c.paper_details),
                  key=lambda d: (d.question_similarity, d.paper_id)).paper_id
    main = next(c for c in source.clusters if c.kind == "main")
    _, state, _ = load_version("fast-map", cfg)
    by_id = {p.id: p for p in state.papers}
    edge = lambda cid, ids: Connection(id=cid, kind="within_cluster", paper_ids=ids, cluster_ids=["X"], description="d",
                                       evidence=[Evidence(paper_id=i, quote=by_id[i].abstract[:30]) for i in ids])
    from litagent.cluster_state import save_version, set_head
    from litagent.finding_analysis import FindingAnalysis
    arrays = load_version("fast-map", cfg)[2]
    analysed = source.model_copy(deep=True, update={"run_id": "fast-map-a", "parent_run_id": "fast-map", "version_token": None,
        "connections": [edge("keep", main.paper_ids[:2]), edge("drop", [main.paper_ids[0], leaving])],
        "analysis": FindingAnalysis(request_id="r", source_run_id="fast-map", completed_stages=["connections", "gaps"])})
    save_version(analysed, state.papers, state.effort, arrays, cfg, backup_papers=state.backup_papers)
    set_head(analysed, cfg)
    child = refresh_map("fast-map-a", analysed.version_token, cfg)
    assert leaving in child.refresh["swapped_out"] and [c.id for c in child.connections] == ["keep"]
    assert child.analysis.pending_stages == ["connections", "gaps"]


def test_refresh_needs_a_pool_and_the_active_version(fast_map, tmp_path):
    source, cfg, _ = fast_map
    child = refresh_map("fast-map", source.version_token, cfg)
    with pytest.raises(VersionError, match="active version"):
        refresh_map("fast-map", source.version_token, cfg)
    plain = run_cluster_map([Paper(id=f"N{i}", title=f"Note {i}", source="test") for i in range(3)], QUESTION,
                            Effort.NORMAL, cfg, "no-pool")
    with pytest.raises(VersionError, match="no backup pool"):
        refresh_map("no-pool", plain.version_token, cfg)
    events = [json.loads(line) for line in (tmp_path / f"trace-{child.run_id}.jsonl").read_text().splitlines()]
    assert events[0]["phase"] == "start" and events[-1]["terminal"]
