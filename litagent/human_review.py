"""Human-in-the-loop review points (Human review 1 and 2 in the architecture).

The orchestrator only depends on the Reviewer interface, so the terminal version can be
swapped for the front end later without touching the pipeline.
"""

from __future__ import annotations

from typing import Protocol

from litagent.schemas import HumanFeedback, RetrievalSummary, RunResult


class Reviewer(Protocol):
    def review_papers(self, summary: RetrievalSummary) -> HumanFeedback: ...
    def review_result(self, result: RunResult) -> HumanFeedback: ...


class AutoApproveReviewer:
    """For sample mode, tests and evals: always approves."""

    def review_papers(self, summary: RetrievalSummary) -> HumanFeedback:
        return HumanFeedback(approved=True)

    def review_result(self, result: RunResult) -> HumanFeedback:
        return HumanFeedback(approved=True)


class RequestReviewer(AutoApproveReviewer):
    """For POST /run: never waits for input. If the request carries `feedback`, Human review 1
    rejects once with it (so the Planner re-plans), then everything is approved."""

    def __init__(self, feedback: str | None = None):
        self.feedback = feedback

    def review_papers(self, summary: RetrievalSummary) -> HumanFeedback:
        if self.feedback:
            comment, self.feedback = self.feedback, None
            return HumanFeedback(approved=False, comment=comment)
        return HumanFeedback(approved=True)


class CLIReviewer:
    """Asks in the terminal. TODO: replace with the front end (chat box + thumbs up/down)."""

    def review_papers(self, summary: RetrievalSummary) -> HumanFeedback:
        print("\n=== Human review 1: papers found ===")
        print(summary.summary)
        for p in summary.papers[:10]:
            print(f"  - {p.title} ({p.year})")
        if len(summary.papers) > 10:
            print(f"  ... and {len(summary.papers) - 10} more")
        return _ask(summary.follow_up_question)

    def review_result(self, result: RunResult) -> HumanFeedback:
        print("\n=== Human review 2: results ===")
        for c in result.clusters:
            print(f"  [{c.id}] {c.label} ({len(c.paper_ids)} papers)")
        for g in result.gaps:
            print(f"  Gap in {g.cluster_id}: {g.description}")
        return _ask("Happy with this? Anything to change?")


def _ask(question: str) -> HumanFeedback:
    answer = input(f"{question} [y / or type feedback]: ").strip()
    if answer.lower() in {"", "y", "yes"}:
        return HumanFeedback(approved=True)
    return HumanFeedback(approved=False, comment=answer)
