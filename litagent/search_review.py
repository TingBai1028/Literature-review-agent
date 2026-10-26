"""Human review 1 for the web map: Planner -> Retriever -> Zetaris, then stop for the user.

POST /search runs one planning attempt and returns the plan, the papers (read back through Zetaris)
and the Human review 1 summary. Unlike /run, nothing is approved automatically: the user keeps or
removes papers and sends the kept ones to POST /cluster, or sends feedback plus the returned plan
to re-plan. The re-plan changes only what the feedback asks for (planner.plan with previous_plan).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from litagent.agents import planner, retriever
from litagent.config import EFFORT_PROFILES, Effort, Settings
from litagent.integrations.llm import TokenMeter
from litagent.integrations.zetaris import ZetarisError, ZetarisStore
from litagent.schemas import Paper, SearchPlan, TokenUsage
from litagent.trace import Trace


class SearchResult(BaseModel):
    search_id: str
    status: Literal["ok", "need_topic", "no_results"]
    sample_mode: bool = False
    message_to_user: str | None = None
    plan: SearchPlan | None = None
    papers: list[Paper] = Field(default_factory=list)
    backup_papers: list[Paper] = Field(default_factory=list)  # Fast/Pro: ranked pool that "refresh" swaps in
    summary: str | None = None
    follow_up_question: str | None = None
    warnings: list[str] = Field(default_factory=list)
    usage: TokenUsage | None = None


def run_search(question: str, effort: Effort, settings: Settings, *, feedback: str | None = None,
               previous_plan: SearchPlan | None = None, signed_in: bool = False,
               search_id: str | None = None) -> SearchResult:
    with Trace(settings.logs_dir, search_id) as trace, TokenMeter(EFFORT_PROFILES[effort].token_budget) as meter:
        result = SearchResult(search_id=trace.run_id, status="ok", sample_mode=settings.sample_mode)
        trace.log("orchestrator", "start search review", "plan and retrieve", question, "planner",
                  why=f"Web Human review 1; effort={effort.value}; re-plan={previous_plan is not None}")
        failed = False
        try:
            trace.log("planner", "start", "plan searches", phase="start", message="Planner: turning the question into searches")
            planned = planner.plan(question, effort, settings, feedback, previous_plan)
            if planned.status == "need_topic" or planned.plan is None:
                result.status, result.message_to_user = "need_topic", planned.message_to_user
                trace.log("planner", "check topic", "no clear topic", next_step="ask user", why="Avoid guessing a topic",
                          phase="done", message="Planner: no clear topic, asking you for one")
                return result
            result.plan = plan = planned.plan
            trace.log("planner", "plan", "plan created", plan, "retriever",
                      why=f"{plan.rationale or 'no rationale given'}; defaults used: {plan.used_defaults}", phase="done",
                      message=f"Planner: {len(plan.queries)} search queries, up to {plan.max_papers} papers")
            trace.log("retriever", "start", "search sources", phase="start",
                      message=f"Retriever: searching for up to {plan.max_papers} papers")
            papers, result.backup_papers = retriever.retrieve_pool(plan, settings, signed_in=signed_in)
            if not papers:
                result.status = "no_results"
                result.message_to_user = retriever.no_results_message(plan)
                trace.log("retriever", "retrieve", "0 papers", next_step="ask user to broaden", why=result.message_to_user,
                          phase="done", message="Retriever: no papers found")
                return result
            trace.log("retriever", "retrieve", f"{len(papers)} papers", next_step="zetaris",
                      why="sample papers from data/sample/" if settings.sample_mode else f"queries: {plan.queries}",
                      phase="done", message=f"Retriever: kept {len(papers)} papers", payload={"paper_ids": [p.id for p in papers]})
            result.papers = _through_zetaris(papers, settings, trace.run_id, result)
            summary = retriever.summarise(result.papers, plan, settings)
            result.summary, result.follow_up_question = summary.summary, summary.follow_up_question
            trace.log("human", "review 1", "waiting for the user", f"{len(result.papers)} papers", "user review",
                      why="The web reviewer keeps/removes papers or sends feedback; nothing is auto-approved")
            return result
        except Exception as error:
            failed = True
            trace.error("orchestrator", "search review", error, next_step="return error to caller", terminal=True)
            raise
        finally:
            result.usage = meter.usage
            if not failed:
                trace.log("orchestrator", "finish search review", result.status, phase="done", terminal=True,
                          message=f"Search finished: {result.status}, {len(result.papers)} papers to review")


def _through_zetaris(papers: list[Paper], settings: Settings, run_id: str, result: SearchResult) -> list[Paper]:
    """Write to the paper store and read back through Zetaris, as /run does; fall back to memory."""
    try:
        store = ZetarisStore(sample_mode=settings.sample_mode, timeout_s=settings.zetaris_timeout_s, run_id=run_id)
    except ZetarisError as error:
        result.warnings.append(f"Zetaris unavailable, used the in-memory papers instead ({error})")
        return papers
    store.save_papers(papers)
    stored = store.get_papers()
    if store.fallback_reason:
        result.warnings.append(f"Zetaris unavailable, used the in-memory papers instead ({store.fallback_reason})")
    return stored or papers
