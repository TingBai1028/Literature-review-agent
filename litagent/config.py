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
    num_queries: int  # search queries the Planner writes; more papers -> more phrasings


EFFORT_PROFILES: dict[Effort, EffortProfile] = {
    Effort.NORMAL: EffortProfile(max_papers=30, use_full_text=False, token_budget=50_000, num_queries=2),
    Effort.MEDIUM: EffortProfile(max_papers=60, use_full_text=False, token_budget=100_000, num_queries=3),
    Effort.HIGH: EffortProfile(max_papers=100, use_full_text=True, token_budget=300_000, num_queries=4),
    Effort.ULTRA: EffortProfile(max_papers=150, use_full_text=True, token_budget=600_000, num_queries=4),
}


# Meterless World Model: authors recorded per paper (consortium papers can list hundreds)
WORLD_MODEL_MAX_AUTHORS = 10


@dataclass(frozen=True)
class DefaultCriteria:
    """Used by the Planner when the user doesn't say otherwise (team decision, 22 Oct)."""

    years_back: int = 5
    paper_types: tuple[str, ...] = ("primary", "review")
    # Team decision (24 Oct): no default minimum. Citations only filter when the user gives a number;
    # otherwise the Retriever ranks by citations per year so recent papers aren't penalised.
    min_citations_per_year: float | None = None

    @property
    def year_from(self) -> int:
        return date.today().year - self.years_back


# Nightshift model for every agent. Must be an NVIDIA Nemotron model, set explicitly
# (no automatic routing, which could pick a non-NVIDIA model).
# Nemotron 3 Ultra (550B total / 55B active MoE) through Nightshift's NVIDIA provider (the route the
# NVIDIA award needs). Tested 24 Oct through Nightshift: Ultra answers (0.8 s for a tiny call);
# Nemotron 3 Super and Llama 3.1 Nemotron Ultra return 404 for our NVIDIA account, Llama 3.3 Nemotron
# Super is retired (410), and 3.5 Super VL is excluded by Nightshift for unreliable responses.
# Fallback that also works: "nvidia/nemotron-3.5-lightning-30b-a3b" (slower here, reasons at length).
# llm.py strips <think> blocks before parsing JSON in case reasoning is returned.
NIGHTSHIFT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes"}


@dataclass
class Settings:
    # Sample mode: the whole pipeline runs on data/sample/ with no Zetaris, Nightshift or network
    sample_mode: bool = field(default_factory=lambda: _env_bool("SAMPLE_MODE"))

    # LLM (Meterless Nightshift, OpenAI-compatible)
    llm_model: str = NIGHTSHIFT_MODEL
    llm_timeout_s: float = 60.0  # per model request (rules: 30-90 s)

    # Zetaris SQL requests (rules: 30-60 s)
    zetaris_timeout_s: float = 45.0

    # Whole run: stop between stages and return a partial result after this many seconds
    run_timeout_s: float = field(default_factory=lambda: float(os.getenv("RUN_TIMEOUT_S", "600")))

    # Retriever ranking: share of relevance vs citations per year (team decision, 24 Oct)
    rank_relevance_weight: float = 0.7

    # Clustering
    cluster_similarity_threshold: float = 0.7  # TODO: check against your embedding model on a sample

    # Grading agents: rubric is 3 criteria x 0-3 points = 9 points (Day 4 workshop)
    grade_pass_mark: int = 7
    max_redo_per_stage: int = 1  # one fix, then revise once

    # Outer loop: how many times human feedback can send the run back to the Planner
    max_replans: int = 3

    defaults: DefaultCriteria = field(default_factory=DefaultCriteria)

    logs_dir: str = "logs"
