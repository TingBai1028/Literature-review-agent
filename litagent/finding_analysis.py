"""Run actual scientific finders on immutable cached maps, or resume a partial analysis."""

from __future__ import annotations

import json
import time
import uuid

from openai import OpenAIError

from litagent.agents import connection_finder, gap_finder, grader
from litagent.cluster_state import (VersionError, atomic_json, effective_settings, head, load_version, path_for,
                                    save_version, set_head, version_lock)
from litagent.config import EFFORT_PROFILES, Settings
from litagent.cluster_cards import full_text_ids
from litagent.finding_engine import FindingContext, check_deadline
from litagent.integrations.llm import LLMError, TokenBudgetExceeded, TokenMeter, current_meter
from litagent.integrations.meterless import ResearchWorld
from litagent.schemas import FindingAnalysis
from litagent.trace import Trace, current_trace, mask, new_run_id


STAGES = ("connections", "gaps")  # fixed order: Graph 1 (paper edges), then Graph 2 (gaps)


def _completed_stages(analysis) -> list[str]:
    if analysis is None:
        return []
    # Older partial versions marked production complete only AFTER grading. Their
    # pending *_grade checkpoint still proves that the finder finished and was saved.
    return [stage for stage in STAGES if stage in analysis.completed_stages
            or f"{stage}_grade" in analysis.pending_stages]


def _pending_stages(analysis) -> list[str]:
    return ([f"{stage}_grade" for stage in STAGES
             if stage in analysis.completed_stages and stage not in analysis.grades]
            + [stage for stage in STAGES if stage not in analysis.completed_stages])


def _check_resources(context) -> None:
    check_deadline(context)
    if meter := current_meter():
        meter.check()


def _grade_warning(warning: str, stage: str) -> bool:
    return warning.startswith((f"{stage} grade unavailable", f"{stage} did not pass independent grading"))


def grade_stage(result, stage, output, papers, settings, world, scope: dict) -> None:
    """Grade a finished stage. A grade scores the findings and never gates the next stage (a failing score
    doesn't either), so a grade the grader can't give (timeout, empty answer) leaves the stage complete but
    ungraded: `<stage>_grade` stays pending and a later analysis request retries it. On 26 Oct a missing
    connections grade stopped Graph 2 although all edges were ready. Running out of budget or time still stops."""
    analysis = result.analysis
    result.warnings = [w for w in result.warnings if not _grade_warning(w, stage)]
    try:
        grade = grader.grade(stage, output, papers, settings, **scope, retry_timeout=False)
        if grade.stage != stage:
            raise LLMError("Independent grader returned the wrong finding stage")
    except TokenBudgetExceeded:
        raise
    except (LLMError, OpenAIError) as error:
        if f"{stage}_grade" not in analysis.pending_stages:
            analysis.pending_stages.append(f"{stage}_grade")
        result.warnings.append(f"{stage} grade unavailable ({mask(str(error))}); findings kept ungraded and the next "
                               "stage continues. A new analysis request retries the grade.")
        if trace := current_trace():
            trace.log("grader", "grade " + stage, "unavailable", why=mask(f"{type(error).__name__}: {error}"),
                      next_step="keep the findings ungraded; continue",
                      message=f"Grading {stage} failed ({type(error).__name__}); kept ungraded, analysis continues")
        return
    if f"{stage}_grade" in analysis.pending_stages:
        analysis.pending_stages.remove(f"{stage}_grade")
    analysis.grades[stage] = grade
    world.record_grade(stage, grade)
    if trace := current_trace():
        trace.log("grader", "grade " + stage, f"{grade.total}/9", result=grade,
                  why=grade.reasoning or grade.fix or "Independent source-based finding grade")
    if not grader.passed(grade, settings):
        result.warnings.append(f"{stage} did not pass independent grading; retained without automatic score-driven regeneration.")


def run_finding_stages(result, papers, settings, world, context: FindingContext, stages=STAGES) -> None:
    """Completed tasks survive a provider/budget failure; an explicit new request can resume.
    `stages` limits the run to some stages, so Graph 1 can be delivered before Graph 2 is produced."""
    analysis = result.analysis
    retained = set(analysis.completed_stages)
    stage, phase, written = "connections", "produce", set()

    def assess(stage):
        _check_resources(context)
        grade_stage(result, stage, getattr(result, stage), papers, settings, world, grader.finding_scope(context, stage))
        # A timed-out request or a late successful response can exhaust the run even
        # when it was within budget before the call. Keep its result, then stop.
        _check_resources(context)

    try:
        for stage in (s for s in STAGES if s in stages and s not in retained):
            phase = "produce"
            agent = {"connections": "connection_finder", "gaps": "gap_finder"}[stage]
            if trace := current_trace():
                trace.log(agent, "start", f"find {stage}", phase="start",
                          message={"connections": "Connection finder: linking papers (Graph 1)",
                                   "gaps": "Gap finder: looking for research gaps (Graph 2)"}[stage])
            _check_resources(context)
            if stage == "connections":
                result.connections = connection_finder.find_connections(papers, result.clusters, settings, context=context)
            else:
                result.gaps = gap_finder.find_gaps(papers, result.clusters, result.connections, settings, context=context)
            output = getattr(result, stage)
            {"connections": world.write_connections, "gaps": world.write_gaps}[stage](output)
            written.add(stage)
            if trace := current_trace():
                trace.log(agent, stage, f"{len(output)} {stage}", phase="done",
                          message=f"{'Connection finder' if stage == 'connections' else 'Gap finder'}: {len(output)} {stage} "
                                  f"ready ({'Graph 1' if stage == 'connections' else 'Graph 2'}); grading next",
                          payload={"ids": [item.id for item in output]})
            phase = "grade"
            analysis.completed_stages.append(stage)
            analysis.pending_stages = _pending_stages(analysis)
            assess(stage)
        # Retry old missing grades AFTER new production. A slow Graph 1 grader must
        # not consume Graph 2's budget before the Gap finder even starts. Each grade
        # gets one wrapper call per explicit request (including its bounded repairs).
        for stage in (s for s in STAGES if s in retained and s not in analysis.grades):
            phase = "grade"
            assess(stage)
    except (LLMError, OpenAIError) as error:
        result.status = "partial"
        if stage == "connections" and phase == "produce":
            result.connections = list(context.partial_connections)
        elif stage == "gaps" and phase == "produce":
            result.gaps = list(context.partial_gaps)
        if stage not in written and stage not in retained:
            {"connections": world.write_connections, "gaps": world.write_gaps}[stage](getattr(result, stage))
        result.warnings.append(mask(str(error)) + "; completed finding tasks retained. Resume this partial version with a new analysis request.")
    finally:
        analysis.pending_stages = _pending_stages(analysis)
        analysis.audits = context.audits
    if any(g.coverage.status in {"unavailable", "inconclusive"} for g in result.gaps if getattr(g, "coverage", None)):
        result.warnings.append("Some research hypotheses have unavailable or inconclusive coverage checks; global novelty is not established.")


def _active_or_partial_descendant(source, settings):
    active = head(source.root_run_id, settings)
    current, visited = source, set()
    while current.run_id != active["run_id"] and current.status == "partial" and current.parent_run_id:
        if current.run_id in visited:
            raise VersionError("Invalid cyclic version ancestry")
        visited.add(current.run_id)
        current, _, _ = load_version(current.parent_run_id, settings)
    if current.run_id != active["run_id"]:
        raise VersionError("Source is no longer active; refresh or explicitly activate it before analysis")


def analyze_cluster_map(run_id: str, expected_version_token: str, settings: Settings,
                        request_id: str | None = None, stages: list[str] | None = None,
                        child_run_id: str | None = None):
    """Run the finding stages on a saved map as a new immutable child version. With stages=["connections"] the
    child is Graph 1 (active at once, gaps pending); stages=["gaps"] on that child adds Graph 2 and keeps its edges."""
    request_id = request_id or uuid.uuid4().hex
    stages = [s for s in STAGES if s in (stages or STAGES)]
    source, state, arrays = load_version(run_id, settings)
    if stages == ["gaps"] and "connections" not in _completed_stages(source.analysis):
        raise VersionError("Connections come first: run the connections stage (Graph 1) before gaps", 422)
    with version_lock(settings, source.root_run_id):
        receipt_path = path_for(settings, "cluster-analysis", request_id)
        if receipt_path.exists():
            receipt = json.loads(receipt_path.read_text())
            if (receipt["source_run_id"] != run_id or receipt["source_version_token"] != expected_version_token
                    or receipt.get("stages", list(STAGES)) != stages):
                raise VersionError("Analysis request ID belongs to another source version or stage list")
            if path_for(settings, "cluster-state", receipt["child_run_id"]).exists():
                child, _, _ = load_version(receipt["child_run_id"], settings)
                return child
            raise VersionError("This request already started without committing. Inspect its trace and use a new request ID for a deliberate retry")
        if source.version_token != expected_version_token:
            raise VersionError("Source version token changed; refresh the map")
        _active_or_partial_descendant(source, settings)
        cfg = effective_settings(state, settings)
        # A client-chosen ID lets the UI subscribe to the new version's events before the analysis starts.
        child_id = child_run_id or new_run_id()
        if child_run_id and any(path_for(settings, prefix, child_id, suffix).exists() for prefix, suffix in (
                ("cluster-map", "json"), ("cluster-state", "json"), ("trace", "jsonl"))):
            raise VersionError("Run ID already exists; choose a new ID for the analysis")
        receipt = {"status": "running", "source_run_id": run_id, "source_version_token": expected_version_token,
                   "child_run_id": child_id, "stages": stages}
        with version_lock(settings, child_id):
            atomic_json(receipt_path, receipt)
            try:
                child = _analyze(source, state, arrays, cfg, child_id, request_id, stages)
                if child.status == "done":
                    set_head(child, settings)
                atomic_json(receipt_path, {**receipt, "status": child.status})
                return child
            except Exception:
                atomic_json(receipt_path, {**receipt, "status": "failed"})
                raise


def _analyze(source, state, arrays, cfg, child_id, request_id, stages=STAGES):
    with Trace(cfg.logs_dir, child_id) as trace, TokenMeter(EFFORT_PROFILES[state.effort].token_budget) as meter:
        trace.log("orchestrator", "analyze cached question map", "reuse papers, embeddings, membership and labels",
                  result={"source_run_id": source.run_id, "request_id": request_id},
                  why="Actual source-grounded finders; immutable child version with its own Nightshift partition")
        # Resume checkpoints without reproducing completed findings. With no pending
        # work, an explicit re-analysis still re-evaluates the requested stages.
        completed = _completed_stages(source.analysis)
        resuming = source.status == "partial" or bool(source.analysis and source.analysis.pending_stages)
        kept = [s for s in completed if s not in stages or resuming]
        if "connections" not in kept:
            kept = []  # new connections invalidate dependent gaps
        analysis = FindingAnalysis(request_id=request_id, source_run_id=source.run_id,
            completed_stages=kept,
            grades={k: v.model_copy(deep=True) for k, v in source.analysis.grades.items() if k in kept} if source.analysis else {},
            audits=[a.model_copy(deep=True) for a in source.analysis.audits if a.stage in kept] if source.analysis else [])
        analysis.pending_stages = _pending_stages(analysis)
        child = source.model_copy(deep=True, update={"run_id": child_id, "stage": "findings", "status": "done",
            "parent_run_id": source.run_id, "revision": source.revision + 1, "version_token": uuid.uuid4().hex,
            "regeneration": None, "refresh": None,
            **{s: [item.model_copy(deep=True) for item in getattr(source, s)] if s in kept else [] for s in STAGES},
            "paper_map": None,
            "analysis": analysis,
            "warnings": [w for w in source.warnings if w.startswith(("Sample mode:", "No paper passed", "Cluster map did not pass"))
                         or any(_grade_warning(w, s) for s in kept)]})
        context = FindingContext(question=child.question, similarity=arrays.similarity, use_full_text=child.use_full_text,
            full_text_ids=full_text_ids(child.clusters), cards=child.cluster_cards,
            deadline=time.monotonic() + cfg.run_timeout_s, audits=analysis.audits,
            cache={k: v.model_copy(deep=True) for k, v in state.finding_cache.items()})
        world = ResearchWorld(child_id, cfg.logs_dir)
        world.start_attempt(1, child.question)
        world.add_papers(state.papers)
        world.write_clusters(child.clusters)
        for stage in kept:
            {"connections": world.write_connections, "gaps": world.write_gaps}[stage](getattr(child, stage))
            if stage in analysis.grades:
                world.record_grade(stage, analysis.grades[stage])
        kept_ids = {item.id for s in kept for item in getattr(child, s)}
        context.dependencies.update({k: v.model_copy(deep=True) for k, v in state.finding_dependencies.items() if k in kept_ids})
        if kept:
            trace.log("orchestrator", "reuse completed finding stages", ", ".join(kept),
                      result={"pending_stages": analysis.pending_stages},
                      why="Preserve findings, evidence, audits and dependencies; only unfinished work is retried")
        if child.grade:
            world.record_grade("clusters", child.grade)
        if child.grade is None:
            try:
                check_deadline(context)
                child.grade = grader.grade("clusters", child.clusters, state.papers, cfg)
                world.record_grade("clusters", child.grade)
                if not grader.passed(child.grade, cfg):
                    child.warnings.append("Cluster map did not pass grading; findings remain subject to map quality review.")
            except (LLMError, OpenAIError) as error:
                child.status = "partial"
                child.analysis.pending_stages = ["clusters_grade", "connections", "gaps"]
                child.warnings.append(mask(str(error)))
        if child.grade is not None:
            run_finding_stages(child, state.papers, cfg, world, context, stages)
        child.paper_map, child.usage = world.to_graph_json(), meter.usage
        ids = {f.id for f in [*child.connections, *child.gaps]}
        save_version(child, state.papers, state.effort, arrays, cfg, keys=state.label_keys,
            dependencies={k: v for k, v in context.dependencies.items() if k in ids}, finding_cache=context.cache,
            backup_papers=state.backup_papers)
        trace.log("orchestrator", "save finding version", child.status,
                  result={"connections": len(child.connections), "gaps": len(child.gaps),
                          "pending_stages": child.analysis.pending_stages},
                  why="Grade failures remain visible; source snapshots are unchanged; hypotheses never establish global novelty",
                  phase="done", terminal=True,
                  message=f"Saved version {child.run_id}: {len(child.connections)} connections, {len(child.gaps)} gaps")
        return child
