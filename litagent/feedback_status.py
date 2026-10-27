"""Readable feedback outcomes and saved recovery state shared by updates and analysis resumes."""
from __future__ import annotations

import json
from pathlib import Path

from litagent.cluster_state import atomic_json, head, load_version, path_for

OLD_PAUSED_MESSAGE = "The update did not finish. Saved results are available in Versions; check the status before continuing."
STEP_NAMES = {"clusters": "Update topics", "clusters_grade": "Check topics", "connections": "Build connection graph",
              "connections_grade": "Review connections", "gaps": "Build gap graph", "gaps_grade": "Review gaps"}


def issue(warnings):
    text = " ".join(warnings).lower()
    if any(word in text for word in ("key_missing", "api key", "not configured", "authentication", "unauthorized")):
        return {"code": "configuration", "reason": "The checking service is not configured.",
                "next_step": "The service connection needs to be restored before resuming."}
    if any(word in text for word in ("insufficient", "credit", "balance", "payment required")):
        return {"code": "credits", "reason": "The model service has no remaining credit for this update.",
                "next_step": "Restore service credit, then resume the saved update."}
    if any(word in text for word in ("token budget", "time limit", "budget exceeded")):
        return {"code": "limit", "reason": "This update reached its processing limit.",
                "next_step": "Resume to finish the remaining steps using the saved work."}
    if any(word in text for word in ("timed out", "timeout")):
        return {"code": "timeout", "reason": "The model service took too long to respond.",
                "next_step": "Resume to retry only the unfinished steps."}
    return {"code": "service", "reason": "The model service could not complete this update.",
            "next_step": "Resume when the service is available, or keep using your current graph."}


def can_resume(draft, active_id, settings):
    current = draft
    seen = set()
    while current.run_id != active_id and current.status == "partial" and current.parent_run_id and current.run_id not in seen:
        seen.add(current.run_id)
        current, _, _ = load_version(current.parent_run_id, settings)
    return current.run_id == active_id


def describe(draft, settings):
    active_id = head(draft.root_run_id, settings)["run_id"]
    analysis = draft.analysis
    completed = ["clusters"] + (["clusters_grade"] if draft.grade is not None else [])
    if analysis:
        for stage in ("connections", "gaps"):
            if stage in analysis.completed_stages or f"{stage}_grade" in analysis.pending_stages:
                completed.append(stage)
            if stage in analysis.grades:
                completed.append(f"{stage}_grade")
    pending = [key for key in STEP_NAMES if key not in completed]
    paused = draft.status == "partial"
    resumable = paused and can_resume(draft, active_id, settings)
    problem = issue(draft.warnings) if paused or pending else None
    if paused:
        message = ("Your feedback and revised topics are saved. The update is paused; your current graph has not been replaced. Resume below or keep the current graph."
                   if resumable else "A newer graph is current. Your draft and feedback are saved; open the current graph to continue.")
    elif pending:
        message = "Your updated graph is ready. Some independent checks are still pending. What would you like to improve next?"
    elif draft.sample_mode:
        message = "Sample mode: a demo revision is ready; no model applied your feedback. What would you like to improve next?"
    else:
        message = "Your updated graph is ready. What would you like to improve next?"
    return {"status": "paused" if paused else "complete", "run_id": draft.run_id, "active_run_id": active_id,
            "can_resume": resumable, "completed": completed, "pending": pending,
            "issue": problem, "message": message}


def _read(run_id, settings):
    path = path_for(settings, "graph-feedback", run_id)
    return json.loads(path.read_text()) if path.exists() else {"votes": {}, "messages": []}


def _latest_legacy_draft(active, settings):
    # Recover pre-workflow saved drafts on the current map, without changing historical snapshots.
    for path in sorted(Path(settings.logs_dir).glob("graph-feedback-*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        if path.name.startswith("graph-feedback-request-"):
            continue
        candidate_id = path.stem.removeprefix("graph-feedback-")
        snapshot = path_for(settings, "cluster-map", candidate_id)
        if not snapshot.exists():
            continue
        candidate = json.loads(snapshot.read_text())
        if candidate.get("root_run_id") != active.root_run_id or candidate.get("status") != "partial" or not candidate.get("human_feedback"):
            continue
        draft, _, _ = load_version(candidate_id, settings)
        if can_resume(draft, active.run_id, settings):
            return draft
    return None


def read(run_id, settings):
    source, _, _ = load_version(run_id, settings)
    record = _read(run_id, settings)
    record["version_token"] = source.version_token
    update = record.get("update")
    if update and update["status"] != "dismissed":
        draft, _, _ = load_version(update["run_id"], settings)
        record["update"] = describe(draft, settings)
    elif not update and source.human_feedback:
        record["update"] = describe(source, settings)
    elif not update and source.run_id == head(source.root_run_id, settings)["run_id"]:
        draft = _latest_legacy_draft(source, settings)
        if draft:
            previous = _read(draft.run_id, settings)
            record.update(messages=previous["messages"], update=describe(draft, settings))
    record["messages"] = [{**message, "text": "An earlier update paused; your feedback was saved."}
                          if message["text"] == OLD_PAUSED_MESSAGE else message for message in record["messages"]]
    if record.get("update") and record["update"]["status"] != "dismissed":
        for message in reversed(record["messages"]):
            if message["role"] == "assistant" and message["id"] == record["update"]["run_id"]:
                message["text"] = record["update"]["message"]
                break
    return record


def publish(child, before, settings, *, user_message=None):
    update = describe(child, settings)
    messages = list(before["messages"])
    if user_message and not any(m["id"] == user_message["id"] for m in messages):
        messages.append(user_message)
    messages = [m for m in messages if m["id"] != child.run_id]
    messages.append({"id": child.run_id, "role": "assistant", "text": update["message"]})
    record = {"version_token": child.version_token, "votes": {}, "messages": messages[-50:], "update": update}
    atomic_json(path_for(settings, "graph-feedback", child.run_id), record)
    if child.status == "partial":
        active = _read(update["active_run_id"], settings)
        active.update(messages=record["messages"], update=update)
        # Keep approvals on the graph still in use, since it has not changed.
        active_map, _, _ = load_version(update["active_run_id"], settings)
        active["version_token"] = active_map.version_token
        atomic_json(path_for(settings, "graph-feedback", active_map.run_id), active)
        return active
    return record


def record_resume(source, child, settings):
    """Called under the analysis root lock, after saving the immutable child and moving its head if done."""
    original = _read(source.run_id, settings)
    previous_id = original.get("update", {}).get("active_run_id")
    if not previous_id:
        current = source
        while current.status == "partial" and current.parent_run_id:
            current, _, _ = load_version(current.parent_run_id, settings)
        previous_id = current.run_id
    record = publish(child, read(source.run_id, settings), settings)
    if child.status == "done":
        # Open tabs on the source graph should see the completion rather than an obsolete resume prompt.
        for run_id in {source.run_id, previous_id} - {child.run_id}:
            previous = _read(run_id, settings)
            update = previous.get("update")
            if run_id == source.run_id or not update or update["run_id"] == source.run_id:
                previous.update(messages=record["messages"], update=record["update"])
                atomic_json(path_for(settings, "graph-feedback", run_id), previous)
