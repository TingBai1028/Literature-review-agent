"""Single entry point for LLM calls, so you can swap providers or models in one place."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


def load_prompt(name: str) -> str:
    """Load a prompt file from prompts/, e.g. load_prompt("planner")."""
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def complete_json(system_prompt: str, user_message: str, output_model: type[T], model: str | None = None) -> T:
    """Call the LLM and parse its answer into `output_model`.

    TODO:
    - Pick a provider (see LLM_PROVIDER in .env) and call its SDK here.
    - Ask for JSON that matches output_model.model_json_schema() (most SDKs support structured output).
    - Validate with output_model.model_validate_json(text); on failure, retry once with the error message.
    - Record token usage so the Planner's token budget can be enforced.
    """
    model = model or os.getenv("LLM_MODEL")
    raise NotImplementedError("TODO: implement complete_json for your LLM provider")
