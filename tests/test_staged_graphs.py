"""Two graphs delivered in stages (spec E): Graph 1 (paper edges) first, then Graph 2 (gaps)."""

from dataclasses import replace

import httpx2
import openai
import pytest
from fastapi.testclient import TestClient

from litagent import api
from litagent.agents import connection_finder, gap_finder, grader
from litagent.cluster_regeneration import activate_version, apply_moves, preview_moves
from litagent.cluster_state import VersionError, head, load_version, path_for, save_version, set_head
from litagent.finding_analysis import analyze_cluster_map
from litagent.integrations.llm import LLMError, TokenBudgetExceeded, current_meter
from litagent.schemas import ClusterMove, ConnectionDecisions, GapDrafts, Grade
from tests.test_cluster_regeneration import snapshot
from tests.test_findings import gap_settings, model  # noqa: F401  (shared offline model fixture)


def test_graph_1_is_active_before_gaps_and_graph_2_keeps_its_edges(model, tmp_path):
    root, cfg, _, _ = snapshot(tmp_path, settings=gap_settings(tmp_path))
    graph1 = analyze_cluster_map("root", root.version_token, cfg, "a" * 32, ["connections"])
    assert graph1.connections and graph1.gaps == []
    assert graph1.analysis.completed_stages == ["connections"] and graph1.analysis.pending_stages == ["gaps"]
    assert head("root", cfg)["run_id"] == graph1.run_id  # Graph 1 is the active version while gaps run
    assert not any(schema is GapDrafts for schema, _ in model["calls"])
    calls = len(model["calls"])
    graph2 = analyze_cluster_map(graph1.run_id, graph1.version_token, cfg, "b" * 32, ["gaps"])
    assert graph2.gaps and graph2.connections == graph1.connections
    assert graph2.clusters == graph1.clusters  # same clusters, so the map keeps every paper's position
    assert graph2.analysis.completed_stages == ["connections", "gaps"] and graph2.analysis.pending_stages == []
    assert "connections" in graph2.analysis.grades
    assert not any(schema is ConnectionDecisions for schema, _ in model["calls"][calls:])
    assert head("root", cfg)["run_id"] == graph2.run_id


TIMEOUT = openai.APITimeoutError(request=httpx2.Request("POST", "http://nightshift.test/v1/chat/completions"))


def grader_failing(monkeypatch, failures):
    """The grader raises the next listed error for each stage it is asked about; with none left it grades 8/9."""
    calls = []
    def grade(stage, output, papers, settings, **scope):
        calls.append((stage, scope))
        if failures.get(stage):
            raise failures[stage].pop(0)
        return Grade(stage=stage, accuracy=3, appropriateness=3, actionability=2, reasoning="Quotes support it.")
    monkeypatch.setattr(grader, "grade", grade)
    return calls


@pytest.mark.parametrize("error", [TIMEOUT, LLMError("GradeDraft: model output failed validation twice")])
def test_a_missing_connections_grade_does_not_block_graph_2_and_is_retried(model, monkeypatch, tmp_path, error):
    root, cfg, _, _ = snapshot(tmp_path, settings=gap_settings(tmp_path))
    calls = grader_failing(monkeypatch, {"connections": [error]})
    graph1 = analyze_cluster_map("root", root.version_token, cfg, "a" * 32, ["connections"])
    assert graph1.status == "done" and graph1.connections and "connections" not in graph1.analysis.grades
    assert graph1.analysis.completed_stages == ["connections"]
    assert graph1.analysis.pending_stages == ["connections_grade", "gaps"]
    assert any("connections grade unavailable" in w for w in graph1.warnings)
    assert head("root", cfg)["run_id"] == graph1.run_id
    graph2 = analyze_cluster_map(graph1.run_id, graph1.version_token, cfg, "b" * 32, ["gaps"])
    assert graph2.status == "done" and graph2.gaps and graph2.connections == graph1.connections
    assert graph2.analysis.grades["connections"].total == 8 and graph2.analysis.pending_stages == []
    assert not any("grade unavailable" in w for w in graph2.warnings)
    stage, scope = calls[-1]  # retry is AFTER gaps, from Graph 1's own reviewed pairs
    assert stage == "connections" and scope["reviewed_pairs"]
    assert [s for s, _ in calls][-2:] == ["gaps", "connections"]
    assert graph2.analysis.audits[0] == graph1.analysis.audits[0]


def test_graph_2_still_runs_when_the_connections_grade_fails_again(model, monkeypatch, tmp_path):
    root, cfg, _, _ = snapshot(tmp_path, settings=gap_settings(tmp_path))
    grader_failing(monkeypatch, {"connections": [TIMEOUT, TIMEOUT], "gaps": [TIMEOUT]})
    graph1 = analyze_cluster_map("root", root.version_token, cfg, "a" * 32, ["connections"])
    graph2 = analyze_cluster_map(graph1.run_id, graph1.version_token, cfg, "b" * 32, ["gaps"])
    assert graph2.status == "done" and graph2.gaps and graph2.analysis.completed_stages == ["connections", "gaps"]
    assert graph2.analysis.pending_stages == ["connections_grade", "gaps_grade"] and graph2.analysis.grades == {}
    assert head("root", cfg)["run_id"] == graph2.run_id


def test_one_request_for_both_graphs_continues_past_a_missing_grade(model, monkeypatch, tmp_path):
    root, cfg, _, _ = snapshot(tmp_path, settings=gap_settings(tmp_path))
    grader_failing(monkeypatch, {"connections": [TIMEOUT]})
    both = analyze_cluster_map("root", root.version_token, cfg, "a" * 32)
    assert both.status == "done" and both.connections and both.gaps
    assert both.analysis.pending_stages == ["connections_grade"] and list(both.analysis.grades) == ["gaps"]


def test_running_out_of_budget_while_grading_still_stops(model, monkeypatch, tmp_path):
    root, cfg, _, _ = snapshot(tmp_path, settings=gap_settings(tmp_path))
    grader_failing(monkeypatch, {"connections": [TokenBudgetExceeded("Token budget used")]})
    graph1 = analyze_cluster_map("root", root.version_token, cfg, "a" * 32, ["connections"])
    assert graph1.status == "partial" and graph1.analysis.pending_stages == ["connections_grade", "gaps"]
    assert head("root", cfg)["run_id"] == "root"


def test_late_successful_grade_survives_budget_exhaustion_and_is_not_repeated(model, monkeypatch, tmp_path):
    root, cfg, _, _ = snapshot(tmp_path, settings=gap_settings(tmp_path))
    calls = grader_failing(monkeypatch, {"connections": [TIMEOUT]})
    graph1 = analyze_cluster_map("root", root.version_token, cfg, "7" * 32, ["connections"])
    original_grade = grader.grade

    def late_grade(stage, *args, **kwargs):
        grade = original_grade(stage, *args, **kwargs)
        if stage == "gaps":
            meter = current_meter()
            meter.add(meter.usage.budget, 1)  # usage is known only after the response arrives
        return grade

    monkeypatch.setattr(grader, "grade", late_grade)
    calls.clear()
    partial = analyze_cluster_map(graph1.run_id, graph1.version_token, cfg, "8" * 32, ["gaps"])
    assert partial.status == "partial" and partial.gaps
    assert partial.analysis.completed_stages == ["connections", "gaps"]
    assert partial.analysis.pending_stages == ["connections_grade"]
    assert partial.analysis.grades["gaps"].total == 8
    assert [s for s, _ in calls] == ["gaps"]
    assert head(root.run_id, cfg)["run_id"] == graph1.run_id

    monkeypatch.setattr(connection_finder, "find_connections", lambda *a, **kw: pytest.fail("Connections already finished"))
    monkeypatch.setattr(gap_finder, "find_gaps", lambda *a, **kw: pytest.fail("Gaps already finished"))
    calls.clear()
    resumed = analyze_cluster_map(partial.run_id, partial.version_token, cfg, "9" * 32, ["gaps"])
    assert resumed.status == "done" and not resumed.analysis.pending_stages
    assert resumed.connections == partial.connections and resumed.gaps == partial.gaps
    assert resumed.analysis.grades["gaps"] == partial.analysis.grades["gaps"]
    assert [s for s, _ in calls] == ["connections"]


def test_grade_only_retry_preserves_findings_sources_audits_and_idempotency(model, monkeypatch, tmp_path):
    root, cfg, _, _ = snapshot(tmp_path, settings=gap_settings(tmp_path))
    calls = grader_failing(monkeypatch, {"connections": [TIMEOUT], "gaps": [TIMEOUT]})
    ungraded = analyze_cluster_map("root", root.version_token, cfg, "1" * 32)
    _, old_state, _ = load_version(ungraded.run_id, cfg)
    original = path_for(cfg, "cluster-map", ungraded.run_id).read_bytes()
    monkeypatch.setattr(connection_finder, "find_connections", lambda *a, **kw: pytest.fail("No repeat Connection finder"))
    monkeypatch.setattr(gap_finder, "find_gaps", lambda *a, **kw: pytest.fail("No repeat Gap finder or coverage search"))
    calls.clear()
    retried = analyze_cluster_map(ungraded.run_id, ungraded.version_token, cfg, "2" * 32, ["gaps"])
    assert retried.status == "done" and not retried.analysis.pending_stages
    assert retried.connections == ungraded.connections and retried.gaps == ungraded.gaps
    assert retried.analysis.audits == ungraded.analysis.audits
    assert [s for s, _ in calls] == ["connections", "gaps"]
    assert all(scope["reviewed_pairs"] for _, scope in calls)
    assert not any("grade unavailable" in w for w in retried.warnings)
    assert load_version(retried.run_id, cfg)[1].finding_dependencies == old_state.finding_dependencies
    assert path_for(cfg, "cluster-map", ungraded.run_id).read_bytes() == original
    calls.clear()
    assert analyze_cluster_map(ungraded.run_id, ungraded.version_token, cfg, "2" * 32, ["gaps"]) == retried
    assert not calls
    # A completed but ungraded version stays explicitly selectable in history.
    activate_version(root.run_id, ungraded.run_id, retried.run_id, retried.version_token, cfg)
    assert head(root.run_id, cfg)["run_id"] == ungraded.run_id


def test_legacy_partial_grade_checkpoint_can_start_graph_2_without_reproducing_edges(model, monkeypatch, tmp_path):
    root, cfg, _, _ = snapshot(tmp_path, settings=gap_settings(tmp_path))
    grader_failing(monkeypatch, {"connections": [TIMEOUT]})
    graph1 = analyze_cluster_map("root", root.version_token, cfg, "3" * 32, ["connections"])
    _, state, arrays = load_version(graph1.run_id, cfg)
    graph1.run_id = "legacy"
    graph1.parent_run_id = root.run_id
    graph1.status = "partial"
    graph1.analysis.completed_stages = []  # pre-fix format used by the failed real 50-paper run
    save_version(graph1, state.papers, state.effort, arrays, cfg, keys=state.label_keys,
                 dependencies=state.finding_dependencies, finding_cache=state.finding_cache)
    set_head(root, cfg)
    before = path_for(cfg, "cluster-map", graph1.run_id).read_bytes()
    monkeypatch.setattr(connection_finder, "find_connections", lambda *a, **kw: pytest.fail("Legacy edges were already finished"))
    graph2 = analyze_cluster_map(graph1.run_id, graph1.version_token, cfg, "4" * 32, ["gaps"])
    assert graph2.status == "done" and graph2.connections == graph1.connections and graph2.gaps
    assert graph2.analysis.completed_stages == ["connections", "gaps"]
    assert path_for(cfg, "cluster-map", graph1.run_id).read_bytes() == before


@pytest.mark.parametrize("during", ["produce", "grade"])
def test_deadline_after_finished_work_preserves_it_and_stops_before_graph_2(model, monkeypatch, tmp_path, during):
    root, cfg, _, _ = snapshot(tmp_path, settings=gap_settings(tmp_path))
    clock = [0.0]
    # Only the context deadline checks use this clock; no real sleeping is needed.
    from litagent import finding_engine
    monkeypatch.setattr(finding_engine.time, "monotonic", lambda: clock[0])
    if during == "produce":
        original = connection_finder.find_connections
        def finish(*args, **kwargs):
            result = original(*args, **kwargs)
            clock[0] = cfg.run_timeout_s + 1
            return result
        monkeypatch.setattr(connection_finder, "find_connections", finish)
    else:
        original = grader.grade
        def finish(stage, *args, **kwargs):
            if stage == "connections":
                clock[0] = cfg.run_timeout_s + 1
                raise TIMEOUT
            return original(stage, *args, **kwargs)
        monkeypatch.setattr(grader, "grade", finish)
    monkeypatch.setattr(gap_finder, "find_gaps", lambda *a, **kw: pytest.fail("Deadline must stop the next finder"))
    result = analyze_cluster_map("root", root.version_token, cfg, "5" * 32)
    assert result.status == "partial" and result.connections
    assert result.analysis.completed_stages == ["connections"]
    assert result.analysis.pending_stages == ["connections_grade", "gaps"]
    assert head(root.run_id, cfg)["run_id"] == root.run_id


def test_regeneration_keeps_a_complete_map_active_when_only_finding_grades_fail(model, monkeypatch, tmp_path):
    root, cfg, _, _ = snapshot(tmp_path, settings=gap_settings(tmp_path))
    analyzed = analyze_cluster_map(root.run_id, root.version_token, cfg, "6" * 32)
    grader_failing(monkeypatch, {"connections": [TIMEOUT], "gaps": [TIMEOUT]})
    preview = preview_moves(analyzed.run_id, [ClusterMove(paper_id="A", target_cluster_id="S2")], cfg)
    child = apply_moves(analyzed.run_id, preview.preview_id, cfg)
    assert child.status == "done" and child.analysis.completed_stages == ["connections", "gaps"]
    assert child.regeneration.pending_stages == ["connections_grade", "gaps_grade"]
    assert head(root.run_id, cfg)["run_id"] == child.run_id


def test_gaps_cannot_run_before_connections(model, tmp_path):
    root, cfg, _, _ = snapshot(tmp_path, settings=gap_settings(tmp_path))
    with pytest.raises(VersionError, match="Connections come first"):
        analyze_cluster_map("root", root.version_token, cfg, "c" * 32, ["gaps"])


def test_a_request_id_is_bound_to_its_stage_list(model, tmp_path):
    root, cfg, _, _ = snapshot(tmp_path, settings=gap_settings(tmp_path))
    analyze_cluster_map("root", root.version_token, cfg, "d" * 32, ["connections"])
    with pytest.raises(VersionError, match="stage list"):
        analyze_cluster_map("root", root.version_token, cfg, "d" * 32, ["connections", "gaps"])


def test_staged_analysis_through_the_api(model, tmp_path):
    root, cfg, _, _ = snapshot(tmp_path, settings=gap_settings(tmp_path))
    api.app.dependency_overrides[api.get_settings] = lambda: cfg
    try:
        with TestClient(api.app) as client:
            first = client.post("/cluster/root/analyze", json={"expected_version_token": root.version_token,
                                                               "stages": ["connections"]}).json()["output"]
            assert first["connections"] and not first["gaps"] and first["analysis"]["pending_stages"] == ["gaps"]
            second = client.post(f"/cluster/{first['run_id']}/analyze", json={
                "expected_version_token": first["version_token"], "stages": ["gaps"]}).json()["output"]
            assert second["gaps"] and second["connections"] == first["connections"]
            bad = client.post("/cluster/root/analyze", json={"expected_version_token": root.version_token, "stages": []})
            assert bad.status_code == 422
    finally:
        api.app.dependency_overrides.clear()


def test_gaps_without_a_coverage_search_do_not_break_the_analysis(model, tmp_path):
    root, cfg, _, _ = snapshot(tmp_path, settings=replace(gap_settings(tmp_path), gap_coverage_check=False))
    result = analyze_cluster_map("root", root.version_token, cfg, "e" * 32)
    assert result.gaps and all(g.coverage is None and g.coverage_status == "skipped" for g in result.gaps)
