"""Human votes and feedback regeneration remain explicit, source-grounded, and immutable."""
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from litagent import api, graph_feedback, finding_engine
from litagent.agents import connection_finder, gap_finder, grader
from litagent.cluster_state import VersionError, head, load_version, path_for
from litagent.finding_analysis import analyze_cluster_map
from litagent.graph_feedback import FeedbackClusters, GraphFeedbackRequest, VoteRequest
from litagent.integrations.llm import LLMError
from litagent.schemas import Grade
from tests.test_cluster_regeneration import models, snapshot


@pytest.fixture
def saved(models, tmp_path, monkeypatch):
    source, cfg, papers, arrays = snapshot(tmp_path)
    monkeypatch.setattr(graph_feedback, "build_cards", lambda *args: [])
    monkeypatch.setattr(grader, "grade", lambda stage, *args, **kwargs: Grade(
        stage=stage, accuracy=3, appropriateness=3, actionability=2, reasoning="Controlled source check"))
    return source, cfg, papers, arrays


def body(source, **kwargs):
    return GraphFeedbackRequest(expected_version_token=source.version_token, request_id="a"*32,
                                text="Separate the two side topics and use more precise labels.", run_id="feedback-child", **kwargs)


def planner(monkeypatch, source):
    seen = []

    def complete(prompt, message, schema, **kwargs):
        payload = json.loads(message)
        seen.append(payload)
        spans = {p["id"]: p["spans"][0]["span_id"] for p in payload["papers"]}
        return FeedbackClusters(clusters=[{
            "kind": c.kind, "label": "Revised " + c.label, "rationale": "The revised label follows the human's request and original sources.",
            "paper_ids": c.paper_ids, "evidence": [{"paper_id": pid, "span_id": spans[pid]} for pid in c.paper_ids],
        } for c in source.clusters])

    monkeypatch.setattr(finding_engine, "complete_json", complete)
    return seen


def test_votes_are_persisted_without_changing_the_map_or_calling_models(saved):
    source, cfg, _, _ = saved
    before = path_for(cfg, "cluster-map", source.run_id).read_bytes()
    vote = VoteRequest(expected_version_token=source.version_token, target={"kind": "cluster", "id": "MAIN"}, vote="up")
    state = graph_feedback.vote(source.run_id, vote, cfg)
    assert state["votes"]["cluster:MAIN"]["vote"] == "up"
    assert graph_feedback.read_feedback(source.run_id, cfg) == state
    assert path_for(cfg, "cluster-map", source.run_id).read_bytes() == before
    assert head(source.root_run_id, cfg)["run_id"] == source.run_id


def test_votes_reject_stale_tokens_and_unknown_items(saved):
    source, cfg, _, _ = saved
    for token, ident in [("0"*32, "MAIN"), (source.version_token, "missing")]:
        vote = VoteRequest(expected_version_token=token, target={"kind": "cluster", "id": ident}, vote="down")
        with pytest.raises(VersionError):
            graph_feedback.vote(source.run_id, vote, cfg)
    assert graph_feedback.read_feedback(source.run_id, cfg)["votes"] == {}


def test_feedback_reaches_cluster_connection_and_gap_agents_without_retrieval(saved, monkeypatch):
    source, cfg, _, arrays = saved
    seen = planner(monkeypatch, source)
    fixes = []
    monkeypatch.setattr(connection_finder, "find_connections", lambda *args, fix=None, **kwargs: fixes.append(("connections", fix)) or [])
    monkeypatch.setattr(gap_finder, "find_gaps", lambda *args, fix=None, **kwargs: fixes.append(("gaps", fix)) or [])
    originals = {p: path_for(cfg, p, source.run_id).read_bytes() for p in ["cluster-map", "cluster-state", "world"]}
    out = graph_feedback.regenerate(source.run_id, body(source), cfg)
    child, state, cached = load_version(out["map"]["run_id"], cfg)
    assert child.run_id == "feedback-child" and child.parent_run_id == source.run_id and child.revision == 1
    # The revision returns topics and Connection graph; Gap graph is its own request, with its own time limit.
    assert child.analysis.completed_stages == ["connections"] and child.analysis.pending_stages == ["gaps"]
    assert out["feedback"]["update"]["status"] == "complete" and "gaps" in out["feedback"]["update"]["pending"]
    gaps = analyze_cluster_map(child.run_id, child.version_token, cfg, request_id="b"*32, stages=["gaps"])
    assert gaps.analysis.completed_stages == ["connections", "gaps"] and not gaps.analysis.pending_stages
    assert gaps.human_feedback == body(source).text and head(source.root_run_id, cfg)["run_id"] == gaps.run_id
    assert not graph_feedback.read_feedback(gaps.run_id, cfg)["update"]["pending"]
    assert all(body(source).text in fix for _, fix in fixes)
    assert body(source).text in seen[0]["feedback"] and child.human_feedback == body(source).text
    assert all(c.label.startswith("Revised ") for c in child.clusters)
    assert np.array_equal(cached.paper_vectors, arrays.paper_vectors) and np.array_equal(cached.similarity, arrays.similarity)
    assert all(path_for(cfg, p, source.run_id).read_bytes() == data for p, data in originals.items())
    assert out["feedback"]["messages"][0]["text"] == body(source).text
    assert len(graph_feedback.regenerate(source.run_id, body(source), cfg)["feedback"]["messages"]) == 2
    assert len(seen) == 1 and len(fixes) == 2  # replay never calls an agent again


def test_feedback_request_ids_cannot_be_reused_for_different_text(saved, monkeypatch):
    source, cfg, _, _ = saved
    planner(monkeypatch, source)
    monkeypatch.setattr(connection_finder, "find_connections", lambda *args, **kwargs: [])
    monkeypatch.setattr(gap_finder, "find_gaps", lambda *args, **kwargs: [])
    graph_feedback.regenerate(source.run_id, body(source), cfg)
    with pytest.raises(VersionError, match="different feedback"):
        graph_feedback.regenerate(source.run_id, body(source).model_copy(update={"text": "Different request"}), cfg)


def test_failed_cluster_revision_leaves_the_previous_version_active(saved, monkeypatch):
    source, cfg, _, _ = saved
    def fail(*args, **kwargs):
        raise LLMError("Provider unavailable")
    monkeypatch.setattr(finding_engine, "complete_json", fail)
    with pytest.raises(LLMError):
        graph_feedback.regenerate(source.run_id, body(source), cfg)
    assert head(source.root_run_id, cfg)["run_id"] == source.run_id
    assert not path_for(cfg, "cluster-map", "feedback-child").exists()
    assert json.loads(path_for(cfg, "graph-feedback-request", "a"*32).read_text())["status"] == "failed"


def test_invalid_partition_or_invented_evidence_is_rejected(saved, monkeypatch):
    source, cfg, _, _ = saved
    def invalid(prompt, message, schema, **kwargs):
        return FeedbackClusters(clusters=[{"kind": "main", "label": "Wrong", "rationale": "Bad partition", "paper_ids": ["invented"]}])
    monkeypatch.setattr(finding_engine, "complete_json", invalid)
    with pytest.raises(LLMError, match="source validation"):
        graph_feedback.regenerate(source.run_id, body(source), cfg)
    assert head(source.root_run_id, cfg)["run_id"] == source.run_id


def test_partial_finding_revision_retains_feedback_for_resume(saved, monkeypatch):
    source, cfg, _, _ = saved
    planner(monkeypatch, source)
    def interrupted(*args, **kwargs):
        raise LLMError("Connection verifier unavailable")
    monkeypatch.setattr(connection_finder, "find_connections", interrupted)
    out = graph_feedback.regenerate(source.run_id, body(source), cfg)
    assert out["map"]["status"] == "partial"
    assert head(source.root_run_id, cfg)["run_id"] == source.run_id
    seen = []
    monkeypatch.setattr(connection_finder, "find_connections", lambda *args, fix=None, **kwargs: seen.append(fix) or [])
    monkeypatch.setattr(gap_finder, "find_gaps", lambda *args, fix=None, **kwargs: seen.append(fix) or [])
    child = out["map"]
    resumed = analyze_cluster_map(child["run_id"], child["version_token"], cfg, request_id="resume-feedback")
    assert resumed.status == "done" and seen == [body(source).text, body(source).text]


def test_feedback_routes_validate_and_persist_votes(saved):
    source, cfg, _, _ = saved
    api.app.dependency_overrides[api.get_settings] = lambda: cfg
    try:
        with TestClient(api.app) as client:
            route = f"/cluster/{source.run_id}/feedback"
            assert client.get(route).json()["output"]["votes"] == {}
            assert client.post(route + "/vote", json={"expected_version_token": source.version_token,
                "target": {"kind": "cluster", "id": "MAIN"}, "vote": "up"}).status_code == 200
            assert client.post(route + "/regenerate", json={**body(source).model_dump(), "text": " "}).status_code == 422
            assert client.post(route + "/vote", json={"expected_version_token": source.version_token,
                "target": {"kind": "paper", "id": "M"}, "vote": "up"}).status_code == 422
    finally:
        api.app.dependency_overrides.clear()


def test_repartition_rebuilds_membership_hints_and_uses_new_source_quotes(saved, monkeypatch):
    source, cfg, papers, _ = saved
    def changed(prompt, message, schema, **kwargs):
        payload = json.loads(message)
        spans = {p["id"]: p["spans"][0]["span_id"] for p in payload["papers"]}
        return FeedbackClusters(clusters=[dict(kind=kind, label="Changed group", rationale="Revised from cited source passages",
            paper_ids=members, evidence=[dict(paper_id=pid, span_id=spans[pid]) for pid in members])
            for kind, members in [("main", ["A", "B"]), ("side", ["M", "C", "D", "E"])]])
    monkeypatch.setattr(finding_engine, "complete_json", changed)
    monkeypatch.setattr(connection_finder, "find_connections", lambda *args, **kwargs: [])
    monkeypatch.setattr(gap_finder, "find_gaps", lambda *args, **kwargs: [])
    child = graph_feedback.regenerate(source.run_id, body(source), cfg)["map"]
    by_id = {p.id: p for p in papers}
    assert child["clusters"][0]["paper_ids"] == ["A", "B"]
    ids = {c["id"] for c in child["clusters"]}
    for cluster in child["clusters"]:
        for detail in cluster["paper_details"]:
            assert detail["reason"] == "Revised from cited source passages"
            assert detail["evidence"] and all(e["quote"] in by_id[e["paper_id"]].abstract for e in detail["evidence"])
            assert all(a["cluster_id"] in ids - {cluster["id"]} for a in detail["also_related"])


def test_invented_span_is_rejected_even_with_a_valid_partition(saved, monkeypatch):
    source, cfg, _, _ = saved
    def bad_span(prompt, message, schema, **kwargs):
        return FeedbackClusters(clusters=[dict(kind=c.kind, label=c.label, rationale="Unsupported source",
            paper_ids=c.paper_ids, evidence=[dict(paper_id=pid, span_id="invented-span") for pid in c.paper_ids]) for c in source.clusters])
    monkeypatch.setattr(finding_engine, "complete_json", bad_span)
    with pytest.raises(LLMError, match="source validation"):
        graph_feedback.regenerate(source.run_id, body(source), cfg)
    assert head(source.root_run_id, cfg)["run_id"] == source.run_id


def test_feedback_cannot_overwrite_a_changed_active_head(saved, monkeypatch):
    source, cfg, _, _ = saved
    planner(monkeypatch, source)
    monkeypatch.setattr(connection_finder, "find_connections", lambda *args, **kwargs: [])
    monkeypatch.setattr(gap_finder, "find_gaps", lambda *args, **kwargs: [])
    graph_feedback.regenerate(source.run_id, body(source), cfg)
    next_request = body(source).model_copy(update={"request_id": "b"*32, "run_id": "another-child"})
    with pytest.raises(VersionError, match="active map"):
        graph_feedback.regenerate(source.run_id, next_request, cfg)
    assert not path_for(cfg, "cluster-map", "another-child").exists()


def paused_check(saved, monkeypatch):
    source, cfg, _, _ = saved
    seen = planner(monkeypatch, source)
    def no_checker(*args, **kwargs):
        raise LLMError("Meterless provider request failed: openrouter_key_missing")
    monkeypatch.setattr(grader, "grade", no_checker)
    return graph_feedback.regenerate(source.run_id, body(source), cfg), seen


def test_paused_feedback_keeps_current_map_and_explains_service_problem(saved, monkeypatch):
    source, cfg, _, _ = saved
    graph_feedback.vote(source.run_id, VoteRequest(expected_version_token=source.version_token,
        target={"kind": "cluster", "id": "MAIN"}, vote="up"), cfg)
    before = path_for(cfg, "cluster-map", source.run_id).read_bytes()
    out, _ = paused_check(saved, monkeypatch)
    state = graph_feedback.read_feedback(source.run_id, cfg)
    update = state["update"]
    assert out["map"]["status"] == "partial" and update["status"] == "paused"
    assert update["run_id"] == out["map"]["run_id"] and update["active_run_id"] == source.run_id
    assert update["completed"] == ["clusters"] and "clusters_grade" in update["pending"]
    assert update["issue"]["code"] == "configuration" and "not configured" in update["issue"]["reason"]
    assert update["can_resume"] and "feedback" in update["message"] and "saved" in update["message"]
    assert "Versions" not in state["messages"][-1]["text"]
    assert state["votes"]["cluster:MAIN"]["vote"] == "up"
    assert head(source.root_run_id, cfg)["run_id"] == source.run_id
    assert path_for(cfg, "cluster-map", source.run_id).read_bytes() == before


def test_resume_preserves_feedback_and_does_not_repeat_clustering(saved, monkeypatch):
    source, cfg, _, _ = saved
    out, seen = paused_check(saved, monkeypatch)
    monkeypatch.setattr(finding_engine, "complete_json", lambda *a, **kw: pytest.fail("repeated the saved clustering step"))
    monkeypatch.setattr(grader, "grade", lambda stage, *a, **kw: Grade(stage=stage, accuracy=3, appropriateness=3, actionability=2))
    monkeypatch.setattr(connection_finder, "find_connections", lambda *a, **kw: [])
    monkeypatch.setattr(gap_finder, "find_gaps", lambda *a, **kw: [])
    draft = out["map"]
    child = analyze_cluster_map(draft["run_id"], draft["version_token"], cfg, request_id="resume-saved-feedback")
    state = graph_feedback.read_feedback(child.run_id, cfg)
    assert len(seen) == 1 and child.status == "done"
    assert state["update"]["status"] == "complete" and not state["update"]["pending"]
    assert sum(message["role"] == "user" for message in state["messages"]) == 1
    assert state["messages"][0]["text"] == body(source).text
    assert "updated graph is ready" in state["messages"][-1]["text"]
    assert graph_feedback.read_feedback(source.run_id, cfg)["update"]["status"] == "complete"
    assert graph_feedback.read_feedback(draft["run_id"], cfg)["update"]["status"] == "complete"
    assert head(source.root_run_id, cfg)["run_id"] == child.run_id


def test_keep_current_graph_preserves_draft_and_clears_recovery_prompt(saved, monkeypatch):
    source, cfg, _, _ = saved
    out, _ = paused_check(saved, monkeypatch)
    state = graph_feedback.dismiss(source.run_id, graph_feedback.DismissFeedbackRequest(
        expected_version_token=source.version_token, expected_update_run_id=out["map"]["run_id"]), cfg)
    assert state["update"]["status"] == "dismissed"
    assert graph_feedback.read_feedback(source.run_id, cfg)["update"]["status"] == "dismissed"
    assert path_for(cfg, "cluster-map", out["map"]["run_id"]).exists()
    assert head(source.root_run_id, cfg)["run_id"] == source.run_id
    assert "Kept your current graph" in state["messages"][-1]["text"]


def test_stale_dismissal_and_duplicate_rebuild_are_rejected(saved, monkeypatch):
    source, cfg, _, _ = saved
    out, seen = paused_check(saved, monkeypatch)
    with pytest.raises(VersionError, match="changed"):
        graph_feedback.dismiss(source.run_id, graph_feedback.DismissFeedbackRequest(
            expected_version_token=source.version_token, expected_update_run_id="different-update"), cfg)
    with pytest.raises(VersionError, match="Resume"):
        graph_feedback.regenerate(source.run_id, body(source).model_copy(update={"request_id": "b"*32, "run_id": "duplicate-draft"}), cfg)
    assert len(seen) == 1
    # Replaying the original request is still safe and returns the saved result.
    assert graph_feedback.regenerate(source.run_id, body(source), cfg)["map"]["run_id"] == out["map"]["run_id"]


def test_legacy_saved_draft_is_recovered_without_editing_its_snapshot(saved, monkeypatch):
    source, cfg, _, _ = saved
    out, _ = paused_check(saved, monkeypatch)
    child = out["map"]
    path_for(cfg, "graph-feedback", source.run_id).unlink()
    old_path = path_for(cfg, "graph-feedback", child["run_id"])
    record = json.loads(old_path.read_text())
    record.pop("update")
    record["messages"][-1]["text"] = graph_feedback.feedback_status.OLD_PAUSED_MESSAGE
    old_path.write_text(json.dumps(record))
    snapshot_before = path_for(cfg, "cluster-map", child["run_id"]).read_bytes()
    state = graph_feedback.read_feedback(source.run_id, cfg)
    assert state["update"]["run_id"] == child["run_id"] and state["update"]["can_resume"]
    assert "check the status" not in state["messages"][-1]["text"]
    assert path_for(cfg, "cluster-map", child["run_id"]).read_bytes() == snapshot_before


def test_failed_resume_keeps_saved_topics_and_advances_only_the_recovery_checkpoint(saved, monkeypatch):
    source, cfg, _, _ = saved
    out, seen = paused_check(saved, monkeypatch)
    draft = out["map"]
    monkeypatch.setattr(finding_engine, "complete_json", lambda *a, **kw: pytest.fail("rebuilt topics during resume"))
    resumed = analyze_cluster_map(draft["run_id"], draft["version_token"], cfg, request_id="paused-again")
    state = graph_feedback.read_feedback(source.run_id, cfg)
    assert resumed.status == "partial" and len(seen) == 1
    assert state["update"]["run_id"] == resumed.run_id and state["update"]["can_resume"]
    assert state["update"]["completed"] == ["clusters"]
    assert sum(m["role"] == "user" for m in state["messages"]) == 1
    assert head(source.root_run_id, cfg)["run_id"] == source.run_id
