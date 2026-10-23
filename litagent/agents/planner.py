"""1. Planner agent. Spec: docs/agents/planner.md

Turns the user's question into a SearchPlan. If there is no clear topic, it returns
status="need_topic" with a friendly prompt instead of guessing.

The LLM only fills a small draft (status, stated criteria, queries, rationale). The code builds
the SearchPlan around it: defaults, paper limit, token budget and number of queries come from config.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from litagent.config import EFFORT_PROFILES, Effort, Settings
from litagent.integrations.llm import complete_json, load_prompt
from litagent.schemas import PlannerResult, SearchCriteria, SearchPlan

NEED_TOPIC_MESSAGE = (
    "Happy to help with your literature review! What topic or research question "
    "would you like me to look into?"
)


class PlannerDraft(BaseModel):
    """What the LLM returns. Effort, limits and defaults are set in code, not by the model."""

    status: Literal["ok", "need_topic"]
    message_to_user: str | None = Field(default=None, description="Only for need_topic: a friendly question asking for a topic")
    criteria: SearchCriteria | None = Field(default=None, description="Only what the user stated; leave other fields empty")
    queries: list[str] = Field(default_factory=list, description="Search strings for scholarly APIs")
    rationale: str = Field(default="", description="One sentence: why these criteria and queries, or why there is no topic")

    @model_validator(mode="after")
    def _complete(self) -> PlannerDraft:
        # These errors go back to the model in complete_json's one retry
        if self.status == "ok":
            if self.criteria is None or not self.criteria.topic.strip():
                raise ValueError("status 'ok' needs criteria with a topic")
            if not any(q.strip() for q in self.queries):
                raise ValueError("status 'ok' needs at least one search query")
        elif not (self.message_to_user or "").strip():
            raise ValueError("status 'need_topic' needs a friendly message_to_user")
        return self


def plan(
    question: str,
    effort: Effort,
    settings: Settings,
    feedback: str | None = None,
    previous_plan: SearchPlan | None = None,
) -> PlannerResult:
    """`feedback` and `previous_plan` come from a human review; the new plan changes only what the feedback asks."""
    if not question.strip():
        return PlannerResult(status="need_topic", message_to_user=NEED_TOPIC_MESSAGE)
    if settings.sample_mode:
        return _fake_plan(question, effort, settings)

    num_queries = EFFORT_PROFILES[effort].num_queries
    user_message = _user_message(question, num_queries, feedback, previous_plan)
    draft = complete_json(load_prompt("planner"), user_message, PlannerDraft, settings=settings, agent_name="planner")
    if draft.status == "need_topic":
        return PlannerResult(status="need_topic", message_to_user=draft.message_to_user)

    search_plan = SearchPlan(
        question=question,
        criteria=draft.criteria,
        queries=_clean_queries(draft.queries, num_queries),
        effort=effort,
        max_papers=0,
        token_budget=0,
        rationale=draft.rationale or None,
    )
    return PlannerResult(status="ok", plan=apply_defaults(search_plan, settings))


def _user_message(question: str, num_queries: int, feedback: str | None, previous_plan: SearchPlan | None) -> str:
    payload: dict = {"question": question, "current_year": date.today().year, "number_of_queries": num_queries}
    if previous_plan is not None:
        payload["previous_plan"] = {
            "criteria": previous_plan.criteria.model_dump(mode="json"),
            "queries": previous_plan.queries,
            "filled_by_defaults": previous_plan.used_defaults,
        }
    if feedback:
        payload["feedback"] = feedback
    return json.dumps(payload, ensure_ascii=False)


def _clean_queries(queries: list[str], limit: int) -> list[str]:
    """Strip, drop blanks and case-insensitive duplicates, keep at most `limit`."""
    seen: set[str] = set()
    out = []
    for q in (q.strip() for q in queries):
        if q and q.lower() not in seen:
            seen.add(q.lower())
            out.append(q)
    return out[:limit]


def apply_defaults(plan: SearchPlan, settings: Settings) -> SearchPlan:
    """Fill any criteria the user didn't give, and record which defaults were used."""
    d = settings.defaults
    c = plan.criteria
    used = list(plan.used_defaults)
    # Don't add a start year that would contradict a user's end year ("before 2015")
    if c.year_from is None and (c.year_to is None or c.year_to >= d.year_from):
        c.year_from = d.year_from
        used.append(f"year_from={d.year_from}")
    if not c.paper_types:
        c.paper_types = list(d.paper_types)
        used.append("paper_types=primary+review")
    if c.min_citations_per_year is None and d.min_citations_per_year is not None:
        c.min_citations_per_year = d.min_citations_per_year
        used.append(f"min_citations_per_year={d.min_citations_per_year}")

    profile = EFFORT_PROFILES[plan.effort]
    plan.max_papers = profile.max_papers
    plan.token_budget = profile.token_budget
    plan.used_defaults = used
    return plan


def _fake_plan(question: str, effort: Effort, settings: Settings) -> PlannerResult:
    if len(question.split()) < 3:  # crude stand-in for "no clear topic"
        return PlannerResult(status="need_topic", message_to_user=NEED_TOPIC_MESSAGE)
    fake = SearchPlan(
        question=question,
        criteria=SearchCriteria(topic=question, paper_types=[]),
        queries=[question],
        effort=effort,
        max_papers=0,
        token_budget=0,
    )
    return PlannerResult(status="ok", plan=apply_defaults(fake, settings))
