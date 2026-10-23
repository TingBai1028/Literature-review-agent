"""Orchestrator: runs the agents in the order shown in ARCHITECTURE.md.

Loops:
- No topic -> return a friendly prompt to the user.
- Human review 1 or 2 not satisfied -> back to the Planner with the user's feedback.
- Grading agent fails a stage -> redo that stage once with the grader's fix,
  then continue with a warning (TODO: decide whether to ask the user instead).
"""

from __future__ import annotations

from typing import Callable, TypeVar

from litagent.agents import clusterer, connection_finder, gap_finder, grader, planner, retriever
from litagent.config import Effort, Settings
from litagent.human_review import Reviewer
from litagent.integrations.meterless import WorldModel
from litagent.integrations.zetaris import ZetarisStore
from litagent.schemas import RunResult
from litagent.trace import Trace

T = TypeVar("T")


def run_pipeline(
    question: str,
    effort: Effort,
    reviewer: Reviewer,
    settings: Settings | None = None,
    signed_in: bool = False,
) -> RunResult:
    settings = settings or Settings()
    trace = Trace(settings.runs_dir)
    store = ZetarisStore(dry_run=settings.dry_run)
    world = WorldModel()
    feedback: str | None = None

    for attempt in range(1, settings.max_replans + 1):
        # ----- 1. Planner -----
        planned = planner.plan(question, effort, settings, feedback)
        if planned.status == "need_topic" or planned.plan is None:
            trace.log("planner", "check topic", "no clear topic", next_step="ask user", why="Avoid guessing a topic")
            return RunResult(run_id=trace.run_id, status="need_topic", message_to_user=planned.message_to_user)
        plan = planned.plan
        trace.log("planner", f"plan (attempt {attempt})", "plan created", plan, "retriever", why=f"defaults used: {plan.used_defaults}")

        # ----- 2. Retriever -> Zetaris -----
        papers = retriever.retrieve(plan, settings, signed_in=signed_in)
        store.save_papers(papers)
        world.add_papers(papers)
        trace.log("retriever", "retrieve", f"{len(papers)} papers", next_step="human review 1")

        # ----- Human review 1 -----
        fb = reviewer.review_papers(retriever.summarise(papers, plan, settings))
        if not fb.approved:
            feedback = fb.comment
            trace.log("human", "review 1", "not satisfied", fb.comment, "planner", why="User feedback")
            continue
        trace.log("human", "review 1", "approved", next_step="clusterer")
        papers = store.get_papers()

        result = RunResult(run_id=trace.run_id, status="done", plan=plan, papers=papers)

        # ----- 3. Clusterer + grading -----
        result.clusters = _graded_stage(
            "clusters", lambda fix: clusterer.cluster(papers, effort, settings, fix), papers, settings, trace, result
        )
        world.write_clusters(result.clusters)

        # ----- 4. Connection finder + grading -----
        result.connections = _graded_stage(
            "connections",
            lambda fix: connection_finder.find_connections(papers, result.clusters, settings, fix),
            papers, settings, trace, result,
        )
        world.write_connections(result.connections)

        # ----- 5. Gap finder + grading -----
        result.gaps = _graded_stage(
            "gaps",
            lambda fix: gap_finder.find_gaps(papers, result.clusters, result.connections, settings, fix),
            papers, settings, trace, result,
        )
        world.write_gaps(result.gaps)

        # ----- Human review 2 -----
        # TODO: the front end renders world.to_graph_json() as the paper map
        fb = reviewer.review_result(result)
        if fb.approved:
            trace.log("human", "review 2", "approved", next_step="done")
            return result
        feedback = fb.comment
        trace.log("human", "review 2", "follow-up", fb.comment, "planner", why="User feedback")

    trace.log("orchestrator", "stop", "max replans reached", why=f"limit {settings.max_replans}")
    return RunResult(run_id=trace.run_id, status="max_replans_reached", message_to_user="Let's narrow the question down together.")


def _graded_stage(
    stage: grader.Stage,
    produce: Callable[[str | None], list[T]],
    papers,
    settings: Settings,
    trace: Trace,
    result: RunResult,
) -> list[T]:
    fix: str | None = None
    for attempt in range(settings.max_redo_per_stage + 1):
        output = produce(fix)
        g = grader.grade(stage, output, papers, settings)
        ok = grader.passed(g, settings)
        trace.log(
            "grader", f"grade {stage} (attempt {attempt + 1})", f"{g.total}/9 {'pass' if ok else 'fail'}",
            g, "next stage" if ok else f"redo {stage}", why=g.fix or g.reasoning,
        )
        if ok:
            return output
        fix = g.fix
    result.warnings.append(f"{stage} did not pass grading after {settings.max_redo_per_stage + 1} attempts")
    return output
