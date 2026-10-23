"""1. Planner agent. Spec: docs/agents/planner.md

Turns the user's question into a SearchPlan. If there is no clear topic, it returns
status="need_topic" with a friendly prompt instead of guessing.
"""

from __future__ import annotations

from litagent.config import EFFORT_PROFILES, Effort, Settings
from litagent.integrations.llm import complete_json, load_prompt
from litagent.schemas import PlannerResult, SearchCriteria, SearchPlan

NEED_TOPIC_MESSAGE = (
    "Happy to help with your literature review! What topic or research question "
    "would you like me to look into?"
)


def plan(question: str, effort: Effort, settings: Settings, feedback: str | None = None) -> PlannerResult:
    if settings.dry_run:
        return _fake_plan(question, effort, settings)

    # TODO: call the LLM with prompts/planner.md. Include the user's feedback from a
    # human review (if any) so the new plan changes what the user asked to change.
    user_message = f"Question: {question}\nEffort: {effort.value}\nUser feedback on previous results: {feedback or 'none'}"
    result = complete_json(load_prompt("planner"), user_message, PlannerResult)
    if result.status == "ok" and result.plan:
        result.plan = apply_defaults(result.plan, settings)
    return result


def apply_defaults(plan: SearchPlan, settings: Settings) -> SearchPlan:
    """Fill any criteria the user didn't give, and record which defaults were used."""
    d = settings.defaults
    c = plan.criteria
    used = list(plan.used_defaults)
    if c.year_from is None:
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
