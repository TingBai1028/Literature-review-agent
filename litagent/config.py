"""Settings, effort levels and default search criteria.

Change numbers here, not inside the agents, so the whole team tunes one place.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from dotenv import load_dotenv

load_dotenv()


class Effort(str, Enum):
    NORMAL = "normal"
    MEDIUM = "medium"
    HIGH = "high"
    ULTRA = "ultra"


@dataclass(frozen=True)
class EffortProfile:
    max_papers: int
    use_full_text: bool  # False = metadata only, True = download and read PDFs
    token_budget: int  # TODO: tune once you measure real token usage


EFFORT_PROFILES: dict[Effort, EffortProfile] = {
    Effort.NORMAL: EffortProfile(max_papers=30, use_full_text=False, token_budget=50_000),
    Effort.MEDIUM: EffortProfile(max_papers=60, use_full_text=False, token_budget=100_000),
    Effort.HIGH: EffortProfile(max_papers=100, use_full_text=True, token_budget=300_000),
    Effort.ULTRA: EffortProfile(max_papers=150, use_full_text=True, token_budget=600_000),
}


@dataclass(frozen=True)
class DefaultCriteria:
    """Used by the Planner when the user doesn't say otherwise (team decision, 22 Oct)."""

    years_back: int = 5
    paper_types: tuple[str, ...] = ("primary", "review")
    min_citations_per_year: float | None = None  # TODO: decide whether to filter or only rank

    @property
    def year_from(self) -> int:
        return date.today().year - self.years_back


@dataclass
class Settings:
    dry_run: bool = field(default_factory=lambda: os.getenv("DRY_RUN", "false").lower() == "true")

    # Clustering
    cluster_similarity_threshold: float = 0.7  # TODO: check against your embedding model on a sample

    # Grading agents: rubric is 3 criteria x 0-3 points = 9 points (Day 4 workshop)
    grade_pass_mark: int = 7
    max_redo_per_stage: int = 1  # one fix, then revise once

    # Outer loop: how many times human feedback can send the run back to the Planner
    max_replans: int = 3

    defaults: DefaultCriteria = field(default_factory=DefaultCriteria)

    runs_dir: str = "runs"
