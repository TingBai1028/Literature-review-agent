"""Human votes and whole-graph feedback, with immutable revisions and replay-safe model requests."""
from __future__ import annotations

import json
import time
import uuid
from collections import Counter
from typing import Literal

import numpy as np
from openai import OpenAIError
from pydantic import BaseModel, ConfigDict, Field

from litagent.agents import grader
from litagent import feedback_status
from litagent.cluster_cards import build_cards, full_text_ids
from litagent.cluster_state import (VersionError, atomic_json, digest, effective_settings, head, load_version,
                                    path_for, save_version, set_head, version_lock)
from litagent.config import EFFORT_PROFILES, Settings
from litagent.finding_analysis import run_finding_stages
from litagent.finding_engine import FindingContext, now, request, resolve_evidence, sources
from litagent.integrations.llm import LLMError, TokenMeter
from litagent.integrations.meterless import ResearchWorld
from litagent.question_clusters import attach_alternatives, cluster_id
from litagent.schemas import EvidenceReference, FindingAnalysis, PaperClusterDetail, QuestionCluster
from litagent.trace import Trace, mask, new_run_id


class FeedbackTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["cluster", "connection", "gap"]
    id: str = Field(min_length=1, max_length=200)


class VoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version_token: str = Field(pattern=r"^[a-f0-9]{32}$")
    target: FeedbackTarget
    vote: Literal["up", "down"]


class GraphFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version_token: str = Field(pattern=r"^[a-f0-9]{32}$")
    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    text: str = Field(min_length=1, max_length=4000)
    target: FeedbackTarget | None = None
    run_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._-]{1,64}$")


class DismissFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version_token: str = Field(pattern=r"^[a-f0-9]{32}$")
    expected_update_run_id: str = Field(pattern=r"^[A-Za-z0-9._-]{1,64}$")


class FeedbackCluster(BaseModel):
    kind: Literal["main", "foundation", "side"]
    label: str = Field(min_length=1, max_length=240)
    rationale: str = Field(min_length=1)
    paper_ids: list[str] = Field(min_length=1)
    evidence: list[EvidenceReference] = Field(default_factory=list)


class FeedbackClusters(BaseModel):
    clusters: list[FeedbackCluster] = Field(min_length=1)


def _target(source, target):
    items = getattr(source, {"cluster": "clusters", "connection": "connections", "gap": "gaps"}[target.kind])
    item = next((item for item in items if item.id == target.id), None)
    if item is None:
        raise VersionError("This feedback item does not exist in the selected map", 404)
    return item


def read_feedback(run_id: str, settings: Settings) -> dict:
    return feedback_status.read(run_id, settings)


def dismiss(run_id: str, body: DismissFeedbackRequest, settings: Settings) -> dict:
    source, _, _ = load_version(run_id, settings)
    with version_lock(settings, source.root_run_id):
        if source.version_token != body.expected_version_token or head(source.root_run_id, settings)["run_id"] != run_id:
            raise VersionError("Open the current graph before keeping it")
        record = read_feedback(run_id, settings)
        update = record.get("update")
        if not update or update["run_id"] != body.expected_update_run_id:
            raise VersionError("The feedback update changed; refresh to see its latest progress")
        record["update"] = {**update, "status": "dismissed", "can_resume": False}
        record["messages"].append({"id": uuid.uuid4().hex, "role": "assistant", "text":
            "Kept your current graph. Your feedback and the saved draft are still available." if update["status"] == "paused"
            else "You can continue with this graph and give more feedback. Pending checks remain visible in Reasoning."})
        record["messages"] = record["messages"][-50:]
        atomic_json(path_for(settings, "graph-feedback", run_id), record)
        return record


def vote(run_id: str, body: VoteRequest, settings: Settings) -> dict:
    source, _, _ = load_version(run_id, settings)
    with version_lock(settings, source.root_run_id):
        if source.version_token != body.expected_version_token:
            raise VersionError("The map changed; reload it before giving feedback")
        _target(source, body.target)
        record = read_feedback(run_id, settings)
        record["votes"][f"{body.target.kind}:{body.target.id}"] = {"vote": body.vote, "at": now()}
        atomic_json(path_for(settings, "graph-feedback", run_id), record)
        return record


def regenerate(run_id: str, body: GraphFeedbackRequest, settings: Settings) -> dict:
    text = body.text.strip()
    if not text:
        raise VersionError("Write feedback before regenerating the graph", 422)
    source, state, arrays = load_version(run_id, settings)
    fingerprint = digest({"source": run_id, **body.model_dump(exclude={"run_id"})})
    receipt_path = path_for(settings, "graph-feedback-request", body.request_id)
    with version_lock(settings, "feedback-" + body.request_id):
        if receipt_path.exists():
            receipt = json.loads(receipt_path.read_text())
            if receipt["fingerprint"] != fingerprint:
                raise VersionError("Feedback request ID belongs to different feedback")
            if receipt["status"] in {"done", "partial"}:
                child, _, _ = load_version(receipt["run_id"], settings)
                feedback_id = head(child.root_run_id, settings)["run_id"] if child.status == "partial" else child.run_id
                return {"map": child.model_dump(mode="json"), "feedback": read_feedback(feedback_id, settings)}
            raise VersionError("This feedback request already started; inspect its status or submit a new request")
        with version_lock(settings, source.root_run_id):
            if source.version_token != body.expected_version_token or head(source.root_run_id, settings)["run_id"] != run_id:
                raise VersionError("Open the active map before regenerating from feedback")
            selected = _target(source, body.target) if body.target else None
            cfg = effective_settings(state, settings)
            child_id = body.run_id or new_run_id()
            if any(path_for(settings, p, child_id).exists() for p in ("cluster-map", "cluster-state", "trace", "world")):
                raise VersionError("Run ID already exists; choose a new ID")
            before = read_feedback(run_id, settings)
            if before.get("update", {}).get("status") == "paused":
                raise VersionError("Resume the saved feedback update or keep the current graph before starting a new update")
            instruction = ("Previous human feedback (latest feedback takes precedence):\n" + source.human_feedback[-6000:]
                           + "\nLatest feedback:\n" + text) if source.human_feedback else text
            if selected:
                item = selected.model_dump(mode="json")
                instruction += "\nFeedback target: " + json.dumps({"kind": body.target.kind,
                    "item": {k: item[k] for k in ("id", "label", "description", "paper_ids", "between_paper_ids", "evidence") if k in item}}, ensure_ascii=False)
            approvals = [key for key, value in before["votes"].items() if value["vote"] == "up"]
            if approvals:
                instruction += "\nPreviously approved items (preserve if still source-supported): " + ", ".join(approvals)
            receipt = {"fingerprint": fingerprint, "run_id": child_id, "status": "running"}
            atomic_json(receipt_path, receipt)
            try:
                child = _regenerate(source, state, arrays, instruction, cfg, child_id, body.request_id)
                if child.status == "done":
                    set_head(child, settings)
                record = feedback_status.publish(child, before, settings,
                    user_message={"id": body.request_id, "role": "user", "text": text})
                atomic_json(receipt_path, {**receipt, "status": child.status})
                return {"map": child.model_dump(mode="json"), "feedback": record}
            except Exception:
                atomic_json(receipt_path, {**receipt, "status": "failed"})
                raise


def _revise_clusters(source, state, arrays, feedback, cfg, context):
    if cfg.sample_mode:
        return [c.model_copy(deep=True) for c in source.clusters]
    source_map = sources(state.papers, cfg, context)

    def validate(proposal):
        members = [pid for c in proposal.clusters for pid in c.paper_ids]
        if Counter(members) != Counter(p.id for p in state.papers):
            raise ValueError("Every original paper must appear exactly once; do not add or remove paper IDs")
        if sum(c.kind == "main" for c in proposal.clusters) != 1:
            raise ValueError("Return exactly one main cluster")
        for c in proposal.clusters:
            if len(c.paper_ids) > 1 or c.evidence:
                resolve_evidence(c.evidence, source_map, set(c.paper_ids), cfg)

    proposal = request("graph_feedback", {"question": source.question, "feedback": feedback,
        "current_clusters": [{"id": c.id, "kind": c.kind, "label": c.label, "paper_ids": c.paper_ids} for c in source.clusters],
        "papers": [{"id": p.id, "title": p.title, **source_map.get(p.id, {"spans": []})} for p in state.papers]},
        FeedbackClusters, validate, cfg, context, "clusters")
    old_details = {d.paper_id: d for c in source.clusters for d in c.paper_details}
    query = arrays.question_vector / np.linalg.norm(arrays.question_vector)
    vectors = arrays.paper_vectors / np.linalg.norm(arrays.paper_vectors, axis=1, keepdims=True)
    scores = np.clip(vectors @ query, -1, 1)
    index = {p.id: i for i, p in enumerate(state.papers)}
    revised = []
    for c in proposal.clusters:
        cid = "MAIN" if c.kind == "main" else ("FOUNDATION-" if c.kind == "foundation" else "SIDE-") + cluster_id(c.paper_ids).removeprefix("SIDE-")
        evidence = resolve_evidence(c.evidence, source_map, set(c.paper_ids), cfg) if c.evidence else []
        details = []
        for pid in c.paper_ids:
            detail = (old_details[pid].model_copy(deep=True) if pid in old_details else
                      PaperClusterDetail(paper_id=pid, question_similarity=float(scores[index[pid]]),
                                         relevance="uncertain", reason=c.rationale))
            detail.reason = c.rationale
            detail.evidence = [quote for quote in evidence if quote.paper_id == pid]
            # Old alternatives refer to the old partition; clear them before the new cluster validates.
            detail.also_related = []
            detail.runner_up_cluster_id = None
            details.append(detail)
        revised.append(QuestionCluster(id=cid, kind=c.kind, question=source.question, label=c.label,
            rationale=c.rationale, role_reason="Reconsidered against original sources after human feedback.",
            paper_ids=c.paper_ids, paper_details=details))
    return attach_alternatives(revised, state.papers, arrays.similarity, cfg)


def _regenerate(source, state, arrays, feedback, cfg, child_id, request_id):
    with Trace(cfg.logs_dir, child_id) as trace, TokenMeter(EFFORT_PROFILES[state.effort].token_budget) as meter:
        trace.log("human", "graph feedback", "regenerate", step_kind="human", result={"feedback": feedback},
                  message="Human feedback received; revising the graph from the original papers")
        child = source.model_copy(deep=True, update={"run_id": child_id, "parent_run_id": source.run_id,
            "revision": source.revision + 1, "version_token": uuid.uuid4().hex, "status": "done",
            "human_feedback": feedback, "stage": "findings", "connections": [], "gaps": [], "grade": None,
            "analysis": FindingAnalysis(request_id=request_id, source_run_id=source.run_id),
            "regeneration": None, "refresh": None, "warnings": [], "paper_map": None})
        context = FindingContext(question=source.question, feedback=feedback, similarity=arrays.similarity,
            use_full_text=source.use_full_text, deadline=time.monotonic() + cfg.run_timeout_s)
        world = ResearchWorld(child_id, cfg.logs_dir)
        world.start_attempt(1, source.question)
        world.add_papers(state.papers)
        clusters_revised = False
        try:
            trace.log("clusterer", "start", "revise clusters", phase="start", message="Revising clusters from your feedback")
            child.clusters = _revise_clusters(source, state, arrays, feedback, cfg, context)
            clusters_revised = True
            child.main_cluster_id = next(c.id for c in child.clusters if c.kind == "main")
            context.full_text_ids = full_text_ids(child.clusters)
            child.cluster_cards = build_cards(state.papers, child.clusters, source.question, cfg)
            context.cards = child.cluster_cards
            world.write_clusters(child.clusters)
            trace.log("clusterer", "clusters", "revised", phase="done", message="Revised clusters are ready")
            child.grade = grader.grade("clusters", child.clusters, state.papers, cfg)
            world.record_grade("clusters", child.grade)
            if not grader.passed(child.grade, cfg):
                child.warnings.append("Revised clusters did not pass independent grading; inspect their source evidence.")
            run_finding_stages(child, state.papers, cfg, world, context)
        except (LLMError, OpenAIError) as error:
            if not clusters_revised:
                trace.error("clusterer", "revise graph", error, next_step="keep previous version", terminal=True)
                raise
            child.status = "partial"
            child.warnings.append(mask(str(error)))
            child.analysis.pending_stages = ["clusters_grade", "connections", "gaps"]
        if cfg.sample_mode:
            child.warnings.append("Sample mode: demo revision only; feedback was recorded but no model changed cluster membership.")
        child.paper_map, child.usage = world.to_graph_json(), meter.usage
        save_version(child, state.papers, state.effort, arrays, cfg, dependencies=context.dependencies,
                     finding_cache=context.cache, backup_papers=state.backup_papers)
        trace.log("orchestrator", "save feedback version", child.status, phase="done", terminal=True,
                  message="Feedback revision saved" if child.status == "done" else "Unfinished feedback revision saved")
        return child
