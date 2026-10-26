"""Two graphs delivered in stages (spec E): Graph 1 (paper edges) first, then Graph 2 (gaps)."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from litagent import api
from litagent.cluster_state import VersionError, head
from litagent.finding_analysis import analyze_cluster_map
from litagent.schemas import ConnectionDecisions, GapDrafts
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
