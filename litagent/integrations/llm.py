"""Single entry point for LLM calls, so you can swap providers or models in one place.

Primary provider: Meterless Nightshift, which accepts OpenAI-format requests, so we use the
official OpenAI client pointed at METERLESS_BASE_URL. NVIDIA Nemotron models are connected
through Nightshift (the NVIDIA key lives in Nightshift's Providers tab, never in this app).
The model is set explicitly in config.NIGHTSHIFT_MODEL.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from litagent.config import Settings
from litagent.trace import current_trace

T = TypeVar("T", bound=BaseModel)

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


class LLMError(RuntimeError):
    """The model could not be reached or did not return valid JSON after one retry."""


def load_prompt(name: str) -> str:
    """Load a prompt file from prompts/, e.g. load_prompt("planner")."""
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def get_client(settings: Settings) -> OpenAI:
    base_url = os.getenv("METERLESS_BASE_URL")
    api_key = os.getenv("METERLESS_RUNTIME_TOKEN")
    if not base_url or not api_key:
        raise LLMError("Set METERLESS_BASE_URL and METERLESS_RUNTIME_TOKEN (see .env.example), or run with SAMPLE_MODE=true.")
    return OpenAI(base_url=base_url, api_key=api_key, timeout=settings.llm_timeout_s, max_retries=1)


def complete_json(
    system_prompt: str,
    user_message: str,
    output_model: type[T],
    model: str | None = None,
    settings: Settings | None = None,
    agent_name: str = "llm",
    client: OpenAI | None = None,
) -> T:
    """Call the LLM and parse its answer into `output_model`.

    Asks for JSON matching output_model's schema, validates it with Pydantic, and retries
    once with the validation error included. Logs the model name and token usage of every call.
    """
    settings = settings or Settings()
    if settings.sample_mode:
        raise LLMError("complete_json was called in sample mode; agents should use their sample branch.")
    model = model or settings.llm_model
    if model.startswith("TODO"):
        raise LLMError("Set NIGHTSHIFT_MODEL in litagent/config.py to a Nemotron model ID from Nightshift's Providers tab.")
    client = client or get_client(settings)

    schema = json.dumps(output_model.model_json_schema(), ensure_ascii=False)
    messages = [
        {
            "role": "system",
            "content": f"{system_prompt}\n\nReply with one JSON object only, matching this JSON Schema:\n{schema}",
        },
        {"role": "user", "content": user_message},
    ]

    for attempt in (1, 2):
        start = time.monotonic()
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
        )
        text = response.choices[0].message.content or ""
        usage = response.usage
        tokens = {"prompt": usage.prompt_tokens, "completion": usage.completion_tokens} if usage else None
        try:
            parsed = output_model.model_validate_json(_clean_json_text(text))
        except ValidationError as e:
            _log(agent_name, f"llm call {output_model.__name__} (attempt {attempt})", "invalid JSON",
                 "retry with error" if attempt == 1 else "raise", str(e), response.model or model, tokens, start)
            if attempt == 2:
                raise LLMError(f"{output_model.__name__}: model output failed validation twice") from e
            messages += [
                {"role": "assistant", "content": text},
                {"role": "user", "content": f"Your JSON did not validate:\n{e}\nReply again with corrected JSON only."},
            ]
            continue
        _log(agent_name, f"llm call {output_model.__name__} (attempt {attempt})", "valid JSON",
             "return", "", response.model or model, tokens, start)
        return parsed
    raise AssertionError("unreachable")


def _clean_json_text(text: str) -> str:
    """Remove reasoning and wrappers around the JSON.

    Nemotron 3 reasons by default and may put its thinking in <think>...</think> before the answer
    (sometimes without the opening tag). Some models also wrap JSON in ```json fences.
    """
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return text


def _log(agent: str, action: str, decision: str, next_step: str, why: str, model: str, tokens, start: float) -> None:
    if trace := current_trace():
        trace.log(agent, action, decision, next_step=next_step, why=why, model=model, tokens=tokens,
                  duration_ms=round((time.monotonic() - start) * 1000))
