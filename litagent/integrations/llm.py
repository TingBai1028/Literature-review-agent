"""Single entry point for LLM calls, so you can swap providers or models in one place.

Primary provider: Meterless Nightshift, which accepts OpenAI-format requests, so we use the
official OpenAI client pointed at METERLESS_BASE_URL. NVIDIA Nemotron models are connected
through Nightshift (the NVIDIA key lives in Nightshift's Providers tab, never in this app).
The model is set explicitly in config.NIGHTSHIFT_MODEL.

Nightshift caches answers, keyed on the user message and the calling app (not the system prompt),
and replays semantically similar messages. A stale or near-duplicate replay would be wrong for us
(an edited prompt ignored, or one paper pair answered with another pair's quotes), so every request
names its app per run (`x-title: litagent-<run_id>`): each run gets its own cache partition.
The cache status Nightshift reports is logged with every call. Nightshift also retrieves
prior answers through H-MEM across app IDs within one scope: every request/repair gets a
fresh meterless-scope so producers, graders, and previous runs cannot share those answers. If the
receipt still reports injected memory, the answer is never used: the request is sent again in a
new scope (settings.llm_memory_retries times), then the call fails.

The OpenAI client never retries by itself. A timed-out request already cost llm_timeout_s, and asking the same
thing again rarely helps (26 Oct: label batches and grades took 2 x 90 s and still failed). Connection errors,
429 and 5xx are retried once, as the client did; a timeout only when the caller has no fallback. A caller with
a batch can instead ask again in two halves (halve_on_timeout).
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from contextvars import ContextVar
from pathlib import Path
from typing import Callable, TypeVar, get_args, get_origin

from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI, OpenAIError, RateLimitError
from pydantic import BaseModel, ValidationError

from litagent.config import Settings
from litagent.parallel import run_parallel
from litagent.schemas import TokenUsage
from litagent.trace import current_trace, mask

T = TypeVar("T", bound=BaseModel)

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
CHARS_PER_TOKEN = 4  # rough estimate when the provider reports no usage


class LLMError(RuntimeError):
    """The model could not be reached or did not return valid JSON after one retry."""


class TokenBudgetExceeded(LLMError):
    """The run has used its effort level's token budget; the orchestrator returns a partial result."""


_current_meter: ContextVar[TokenMeter | None] = ContextVar("current_token_meter", default=None)


class TokenMeter:
    """Counts the tokens of every LLM call in a run (retries included) and enforces the budget.

    The orchestrator opens one per run (`with TokenMeter(budget) as meter:`); complete_json finds it
    through current_meter(), so agents don't have to pass it around.
    """

    def __init__(self, budget: int | None = None):
        self.usage = TokenUsage(budget=budget)
        self._token = None
        self._lock = threading.Lock()  # parallel model calls add usage from several threads

    def __enter__(self) -> TokenMeter:
        self._token = _current_meter.set(self)
        return self

    def __exit__(self, *exc: object) -> None:
        if self._token is not None:
            _current_meter.reset(self._token)

    def add(self, prompt_tokens: int, completion_tokens: int, estimated: bool = False) -> None:
        with self._lock:
            self.usage.prompt_tokens += prompt_tokens
            self.usage.completion_tokens += completion_tokens
            self.usage.llm_calls += 1
            self.usage.estimated_calls += int(estimated)

    def check(self) -> None:
        """Raise before a call once the budget is used up."""
        if self.usage.budget is not None and self.usage.total >= self.usage.budget:
            raise TokenBudgetExceeded(f"Token budget used: {self.usage.total:,} of {self.usage.budget:,} tokens")


def current_meter() -> TokenMeter | None:
    return _current_meter.get()


def load_prompt(name: str) -> str:
    """Load a prompt file from prompts/, e.g. load_prompt("planner")."""
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def get_client(settings: Settings) -> OpenAI:
    base_url = os.getenv("METERLESS_BASE_URL")
    api_key = os.getenv("METERLESS_RUNTIME_TOKEN")
    if not base_url or not api_key:
        raise LLMError("Set METERLESS_BASE_URL and METERLESS_RUNTIME_TOKEN (see .env.example), or run with SAMPLE_MODE=true.")
    return OpenAI(base_url=base_url, api_key=api_key, timeout=settings.llm_timeout_s, max_retries=0)


def complete_json(
    system_prompt: str,
    user_message: str,
    output_model: type[T],
    model: str | None = None,
    settings: Settings | None = None,
    agent_name: str = "llm",
    client: OpenAI | None = None,
    retry_timeout: bool = True,
) -> T:
    """Call the LLM and parse its answer into `output_model`.

    Asks for JSON matching output_model's schema, validates it with Pydantic, and retries
    once with the validation error included. Logs the model name and token usage of every call,
    adds the tokens to the run's TokenMeter, and raises TokenBudgetExceeded before a call once
    the run's budget is used up. `retry_timeout=False` raises APITimeoutError after one timed-out
    request, for callers with a fallback (a pending grade, a smaller batch, an unlabelled cluster).
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
            "content": f"{system_prompt}\n\nReply with one JSON object only, matching this JSON Schema:\n{schema}"
                       f"{_no_echo(output_model)}",
        },
        {"role": "user", "content": user_message},
    ]

    meter = current_meter()
    attempt, discarded, echoes = 1, 0, 0
    while True:
        if meter:
            meter.check()
        start = time.monotonic()
        request_scope = f"litagent-call-{uuid.uuid4().hex}"
        response = _create(client, retry_timeout, agent_name, f"llm call {output_model.__name__} (attempt {attempt})",
                           model=model, messages=messages, response_format={"type": "json_object"},
                           extra_headers={"x-title": _app_name(), "meterless-scope": request_scope})
        text = response.choices[0].message.content or ""
        tokens = _tokens(response.usage, messages, text)
        cache = _cache_status(response)
        memory = _memory_status(response)
        if meter:
            meter.add(tokens["prompt"], tokens["completion"], estimated=tokens.get("estimated", False))
        if memory.get("injected", 0):
            again = discarded < settings.llm_memory_retries
            _log(agent_name, f"llm call {output_model.__name__} (attempt {attempt})", "unexpected answer memory",
                 "discard and ask again in a new scope" if again else "raise",
                 "Prior answers would contaminate independent agents/evaluations", response.model or model,
                 tokens, start, cache, memory)
            if again:
                discarded += 1
                continue
            raise LLMError("Nightshift injected prior-answer memory despite a fresh request scope")
        if memory.get("scope") is not None and memory["scope"] != request_scope:
            raise LLMError("Nightshift did not honor the requested answer-memory scope")
        try:
            parsed = output_model.model_validate_json(_clean_json_text(text))
        except ValidationError as e:
            if echoes < settings.llm_echo_retries and _repeats_input(_clean_json_text(text), user_message):
                echoes += 1
                _log(agent_name, f"llm call {output_model.__name__} (attempt {attempt})", "answer repeated the input",
                     "send the same request again", "Only the request's own fields came back; a repair turn would show "
                     "the model its echo as its own answer", response.model or model, tokens, start, cache, memory)
                continue
            if (parsed := _wrap_bare_items(output_model, _clean_json_text(text))) is not None:
                _log(agent_name, f"llm call {output_model.__name__} (attempt {attempt})", "valid JSON after wrapping",
                     "return", "The answer was the list's items without the one-field wrapper; wrapped in code",
                     response.model or model, tokens, start, cache, memory)
                return parsed
            _log(agent_name, f"llm call {output_model.__name__} (attempt {attempt})", "invalid JSON",
                 "retry with error" if attempt == 1 else "raise", str(e), response.model or model, tokens, start, cache, memory)
            if attempt == 2:
                raise LLMError(f"{output_model.__name__}: model output failed validation twice") from e
            attempt = 2
            messages += [
                {"role": "assistant", "content": text},
                {"role": "user", "content": f"Your JSON did not validate:\n{e}\nReply again with corrected JSON only."},
            ]
            continue
        _log(agent_name, f"llm call {output_model.__name__} (attempt {attempt})", "valid JSON",
             "return", "", response.model or model, tokens, start, cache, memory)
        return parsed


def _create(client: OpenAI, retry_timeout: bool, agent_name: str, action: str, **request):
    for retry in (False, True):
        start = time.monotonic()
        try:
            return client.chat.completions.create(**request)
        except (APIConnectionError, RateLimitError, InternalServerError) as error:
            timeout = isinstance(error, APITimeoutError)
            again = not retry and (retry_timeout or not timeout)
            if trace := current_trace():
                trace.log(agent_name, action, "timeout" if timeout else "provider error",
                          next_step="send again" if again else "raise", why=f"{type(error).__name__}: {mask(str(error))}",
                          level=logging.WARNING, model=request["model"], duration_ms=round((time.monotonic() - start) * 1000))
            if not again:
                raise


def timed_out(error: BaseException) -> bool:
    """The request (or the request an LLMError wraps) got no answer within llm_timeout_s."""
    while error is not None:
        if isinstance(error, APITimeoutError):
            return True
        error = error.__cause__
    return False


R = TypeVar("R")


def halve_on_timeout(ask: Callable[[list], list[R]], items: list, why: str = "") -> tuple[list[R], list, Exception | None]:
    """ask(items); if that times out, ask(first half) and ask(second half) at the same time, once.

    A smaller batch answers sooner (26 Oct: a 4-cluster label batch took 82 of the 90 s limit), so this costs at
    most two timeouts, like the client's old retry, but the second try is likely to finish. `ask` should pass
    retry_timeout=False. Returns (results, items that still failed, their error) so the caller's fallback covers
    only those items. Running out of token budget or time, or a non-model error, still raises.
    """
    try:
        return ask(items), [], None
    except TokenBudgetExceeded:
        raise
    except (LLMError, OpenAIError) as error:
        if len(items) < 2 or not timed_out(error):
            return [], list(items), error
        if trace := current_trace():
            trace.log("llm", "batch timed out", f"ask again as 2 halves of {len(items)} items", level=logging.WARNING,
                      next_step="send both halves at once", why=why or "a smaller request answers sooner")
    half = len(items) // 2
    parts = [items[:half], items[half:]]
    results, failed, last = [], [], None
    for part, (out, error) in zip(parts, run_parallel(ask, parts, 2)):
        if error is None:
            results += out
        elif isinstance(error, TokenBudgetExceeded) or not isinstance(error, (LLMError, OpenAIError)):
            raise error
        else:
            failed, last = failed + list(part), error
    return results, failed, last


def _no_echo(output_model: type[BaseModel]) -> str:
    first = next(iter(output_model.model_fields), None)
    lead = f' (its first key is "{first}")' if first else ""
    return f"\nThe user message is the input. Reply with the output object only{lead}; never repeat the input."


def _repeats_input(text: str, user_message: str) -> bool:
    """The answer is a JSON object whose every field is one of the request's own fields with the same value.

    Nemotron 3 Ultra did this for a technical planner question (27 Oct: 6 of 11 answers were the input's
    question, current_year and number_of_queries) and once for a gap-grader batch.
    """
    try:
        answer, request = json.loads(text), json.loads(user_message)
    except ValueError:
        return False
    return (isinstance(answer, dict) and isinstance(request, dict) and bool(answer)
            and all(k in request and request[k] == v for k, v in answer.items()))


def _wrap_bare_items(output_model: type[T], text: str) -> T | None:
    """Wrap a bare item or bare list for a schema whose only field is a list of objects.

    Real run 27 Oct: for a one-gap batch Nemotron answered GapLabelDecisions with the label object alone, without
    {"labels": [...]}, twice, and Graph 2 ended partial. The item must still validate in full, so an echoed
    request or any other shape still fails.
    """
    if len(output_model.model_fields) != 1:
        return None
    name, field = next(iter(output_model.model_fields.items()))
    item = get_args(field.annotation)[0] if get_origin(field.annotation) is list else None
    if not (isinstance(item, type) and issubclass(item, BaseModel)
            and any(f.is_required() for f in item.model_fields.values())):
        return None  # an item with no required field would accept any object
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return None
    try:
        return output_model.model_validate({name: data})
    except ValidationError:
        return None


def _app_name() -> str:
    """Nightshift partitions its answer cache by app; one partition per run means no replays across runs."""
    trace = current_trace()
    return f"litagent-{trace.run_id}" if trace else "litagent"


def _cache_status(response) -> str | None:
    """Nightshift's compute receipt says whether the answer was computed or replayed ("miss", "exact", ...)."""
    receipt = getattr(response, "meterless", None)
    if isinstance(receipt, dict):
        return (receipt.get("cache") or {}).get("status")
    return None


def _memory_status(response) -> dict:
    """Log only isolation metadata; never read or log retrieved memory contents."""
    metadata = getattr(response, "meterless", None)
    if not isinstance(metadata, dict):
        return {"reported": False}
    receipt = metadata.get("receipt")
    if not isinstance(receipt, dict) or "hmem" not in receipt:
        return {"reported": False, "scope": metadata.get("scope")}
    hmem = receipt["hmem"] or {}
    return {"reported": True, "scope": metadata.get("scope"), "injected": hmem.get("injected", 0)}


def _tokens(usage, messages: list[dict], reply: str) -> dict:
    """Token usage as reported by the provider, or a rough estimate (marked) when it reports none."""
    if usage and usage.prompt_tokens is not None:
        return {"prompt": usage.prompt_tokens, "completion": usage.completion_tokens or 0}
    prompt_chars = sum(len(m["content"]) for m in messages)
    return {"prompt": prompt_chars // CHARS_PER_TOKEN, "completion": len(reply) // CHARS_PER_TOKEN, "estimated": True}


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


def _log(agent: str, action: str, decision: str, next_step: str, why: str, model: str, tokens, start: float,
         cache: str | None = None, memory: dict | None = None) -> None:
    if trace := current_trace():
        trace.log(agent, action, decision, next_step=next_step, why=why, model=model, tokens=tokens,
                  duration_ms=round((time.monotonic() - start) * 1000), nightshift_cache=cache,
                  nightshift_memory=memory)
