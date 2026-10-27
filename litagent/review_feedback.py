"""Submit on the Human review page: the agent that wrote a finding rewrites it with the reviewer's judgement.

A connection goes back to the Connection finder (and its verifier), a gap to the Gap finder's writer, coverage check
and gap grader, each with the verdict and reason as the fix. The result is a new immutable map version, like an
analysis: the rewritten finding replaces the old one, or the finding is dropped when the agent abstains or its check
rejects it. Every other finding is kept, and so are the reviewer's judgements of them.
"""

from __future__ import annotations

import json
import time
import uuid

from litagent.agents import connection_finder, gap_finder
from litagent.cluster_cards import full_text_ids
from litagent.cluster_state import (VersionError, atomic_json, effective_settings, load_version, path_for, save_version,
                                    set_head, version_lock)
from litagent.config import EFFORT_PROFILES, Settings
from litagent.finding_analysis import _active_or_partial_descendant
from litagent.finding_engine import FindingContext
from litagent.finding_review import prepare_review
from litagent.integrations.llm import TokenMeter
from litagent.integrations.meterless import ResearchWorld
from litagent.schemas import FindingDependency
from litagent.trace import Trace, new_run_id

VERDICT_TEXT = {"supported": "supported by the sources", "unsupported": "not supported by the sources",
                "uncertain": "not decidable from the sources (insufficient evidence)"}


def needs_rewrite(annotation: dict) -> bool:
    """A plain "supported" keeps the finding as it is; any other verdict, or any reason, is feedback to act on."""
    return annotation["verdict"] != "supported" or bool(annotation.get("rationale", "").strip())


def feedback_text(kind: str, annotation: dict) -> str:
    reason = annotation.get("rationale", "").strip() or "no reason given"
    quotes = "; ".join(f'{e["paper_id"]}: "{e["quote"][:300]}"' for e in annotation.get("evidence", []))
    return (f"A human reviewer judged the previous {kind} {VERDICT_TEXT[annotation['verdict']]}. Their reason: {reason}."
            + (f" Passages they pointed to: {quotes}." if quotes else "")
            + f" Write the {kind} again so it follows this feedback and is supported by both quotes, or abstain if the"
              " sources don't support one.")


def regenerate(run_id: str, item_id: str, expected_version_token: str, settings: Settings,
               child_run_id: str | None = None):
    """Rewrite one reviewed finding with its submitted judgement; returns the new version and what changed."""
    source, state, arrays = load_version(run_id, settings)
    with version_lock(settings, source.root_run_id):
        if source.version_token != expected_version_token:
            raise VersionError("Source version token changed; refresh the map")
        _active_or_partial_descendant(source, settings)
        pack = prepare_review(run_id, settings)
        item = next((i for i in pack["items"] if i["id"] == item_id), None)
        if item is None:
            raise VersionError("Unknown review item", 404)
        if item["annotation"] is None:
            raise VersionError("Submit a judgement for this item first", 422)
        annotation = item["annotation"]
        if not needs_rewrite(annotation):
            return {"map": source, "changed": "kept", "item_id": item_id}
        if source.sample_mode or settings.sample_mode:
            raise VersionError("Rewriting a finding calls the model; it is not available in sample mode", 422)
        cfg = effective_settings(state, settings)
        child_id = child_run_id or new_run_id()
        if any(path_for(settings, prefix, child_id, suffix).exists() for prefix, suffix in
               (("cluster-map", "json"), ("cluster-state", "json"), ("trace", "jsonl"))):
            raise VersionError("Run ID already exists; choose a new ID")
        with version_lock(settings, child_id):
            try:
                child, changed = _rewrite(source, state, arrays, cfg, child_id, item, annotation)
            except ValueError as error:  # e.g. a paper without text, or a pair that is no longer a candidate
                raise VersionError(str(error), 422) from error
            set_head(child, settings)
            _carry_over_judgements(run_id, child, item_id, settings)
            return {"map": child, "changed": changed, "item_id": item_id}


def _rewrite(source, state, arrays, cfg, child_id, item, annotation):
    kind = "connection" if item["kind"] == "connection" else "gap"
    pair = set(item["paper_ids"])
    with Trace(cfg.logs_dir, child_id) as trace, TokenMeter(EFFORT_PROFILES[state.effort].token_budget) as meter:
        trace.log("human", "review submitted", annotation["verdict"], step_kind="human",
                  result={"item_id": item["id"], "kind": kind, "paper_ids": item["paper_ids"],
                          "reason": annotation.get("rationale", "")},
                  why="The reviewer's judgement goes back to the agent that wrote the finding",
                  message=f"Human review: {kind} judged {annotation['verdict']}; rewriting it with that feedback")
        child = source.model_copy(deep=True, update={"run_id": child_id, "stage": "findings", "status": "done",
            "parent_run_id": source.run_id, "revision": source.revision + 1, "version_token": uuid.uuid4().hex,
            "regeneration": None, "refresh": None, "paper_map": None})
        context = FindingContext(question=child.question, similarity=arrays.similarity, use_full_text=child.use_full_text,
            full_text_ids=full_text_ids(child.clusters), cards=child.cluster_cards,
            deadline=time.monotonic() + cfg.run_timeout_s)
        feedback = feedback_text(kind, annotation)
        old = [f for f in getattr(child, kind + "s") if set(f.paper_ids if kind == "connection" else f.between_paper_ids) == pair]
        if kind == "connection":
            record = connection_finder.rewrite_pair(item["paper_ids"], state.papers, child.clusters, feedback, cfg, context)
            new = record.connections
        else:
            new = gap_finder.rewrite_gap(item["paper_ids"], state.papers, child.clusters, feedback, item["claim"], cfg, context)
        kept = [f for f in getattr(child, kind + "s") if f not in old]
        setattr(child, kind + "s", kept + new)
        changed = "rewritten" if new else "removed" if old else "none"
        child.warnings = [w for w in child.warnings if not w.startswith("Human review rewrote")] + [
            f"Human review rewrote a {kind} on this version; its stage grade was given before the change."]
        world = ResearchWorld(child_id, cfg.logs_dir)
        world.start_attempt(1, child.question)
        world.add_papers(state.papers)
        world.write_clusters(child.clusters)
        world.write_connections(child.connections)
        world.write_gaps(child.gaps)
        child.paper_map, child.usage = world.to_graph_json(), meter.usage
        ids = {f.id for f in [*child.connections, *child.gaps]}
        deps = {k: v for k, v in state.finding_dependencies.items() if k in ids}
        for f in new:  # as the finders record them: the papers and clusters a finding rests on
            deps[f.id] = FindingDependency(global_map=False, cluster_ids=f.cluster_ids if kind == "connection" else [f.cluster_id],
                                           paper_ids=f.paper_ids if kind == "connection" else f.between_paper_ids)
        save_version(child, state.papers, state.effort, arrays, cfg, keys=state.label_keys, dependencies=deps,
                     finding_cache=state.finding_cache, backup_papers=state.backup_papers)
        trace.log("orchestrator", "save reviewed version", changed, phase="done", terminal=True,
                  result={"kind": kind, "paper_ids": item["paper_ids"], "before": [f.description for f in old],
                          "after": [f.description for f in new]},
                  why="The finding was written again with the reviewer's feedback and checked as usual",
                  message={"rewritten": f"Rewrote the {kind} with the reviewer's feedback",
                           "removed": f"Removed the {kind}: rewritten with the feedback, it was not supported",
                           "none": f"No {kind} for this pair after the feedback"}[changed])
        return child, changed


def _carry_over_judgements(source_run_id: str, child, rewritten_item: str, settings: Settings) -> None:
    """Judgements of the other findings stay with the new version; the rewritten one starts unjudged."""
    old_path = path_for(settings, "finding-review", source_run_id)
    if not old_path.exists():
        return
    old = json.loads(old_path.read_text())
    items = {i["id"] for i in prepare_review(child.run_id, settings)["items"]}
    records = {k: v for k, v in old.get("records", {}).items() if k in items and k != rewritten_item}
    history = old.get("history", []) + ([{"item_id": rewritten_item, "annotation": old["records"][rewritten_item]}]
                                        if rewritten_item in old.get("records", {}) else [])
    atomic_json(path_for(settings, "finding-review", child.run_id),
                {"version_token": child.version_token, "corpus_fingerprint": old["corpus_fingerprint"],
                 "records": records, "history": history})
