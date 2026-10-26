"""Run log: one JSON line per step in logs/trace-<run_id>.jsonl, plus a readable [INFO] line on stdout.

Judges reward traces that show how the agent got its answer, so log from day one.
Every event has: timestamp, run_id, agent_name, action, decision, result, next, why, plus
- phase: start | step | partial_result | done | error (progress events, see docs/events.md)
- step_kind: code | llm | human (spec B2; a model name means llm, the human agent means human)
- message: one plain sentence for the activity feed and reasoning panel
- payload: optional data kept whole (bounded by the caller), e.g. paper ids for the live map
- terminal: true on the run's last event, so the event stream knows when to stop
LLM calls add the model that handled the request and token usage.
The same file feeds the live event stream (GET /runs/{run_id}/events), so one log serves
both the map animation and the reasoning text (spec A1, B3).
Secrets are masked before anything is written or printed.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("litagent")

# Values of these variables are replaced with *** wherever they appear in a log line
SECRET_ENV_VARS = (
    "METERLESS_RUNTIME_TOKEN", "ZETARIS_API_KEY", "ZETARIS_PASSWORD", "OPENALEX_API_KEY", "SEMANTIC_SCHOLAR_API_KEY",
    "PAPERS_DB_PASSWORD",
)
_SECRET_PATTERNS = [
    re.compile(r"(://[^:/@\s]+:)[^@\s]+(?=@)"),  # password in a connection URL: postgresql://user:***@host
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"()\bsk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)((?:api[_-]?key|token|password|secret)[\"']?\s*[:=]\s*[\"']?)[^\s\"',}]{4,}"),
]

PHASES = ("start", "step", "partial_result", "done", "error")

_current: ContextVar[Trace | None] = ContextVar("current_trace", default=None)


def setup_logging() -> None:
    """Readable [INFO] lines on stdout. Safe to call more than once."""
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False


def current_trace() -> Trace | None:
    """The trace of the run in progress, so integrations can log without being passed it."""
    return _current.get()


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


class Trace:
    def __init__(self, logs_dir: str = "logs", run_id: str | None = None):
        self.run_id = run_id or new_run_id()
        self.path = Path(logs_dir) / f"trace-{self.run_id}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.events: list[dict[str, Any]] = []
        self._token = None

    def __enter__(self) -> Trace:
        self._token = _current.set(self)
        return self

    def __exit__(self, *exc: object) -> None:
        if self._token is not None:
            _current.reset(self._token)

    def log(
        self,
        agent_name: str,
        action: str,
        decision: str,
        result: Any = None,
        next_step: str = "",
        why: str = "",
        level: int = logging.INFO,
        *,
        phase: str = "step",
        step_kind: str | None = None,
        message: str | None = None,
        payload: Any = None,
        terminal: bool = False,
        **extra: Any,
    ) -> None:
        """`extra` is for optional fields such as model, tokens, duration_ms or error."""
        if phase not in PHASES:
            raise ValueError(f"phase must be one of {PHASES}")
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "agent_name": agent_name,
            "action": action,
            "decision": decision,
            "result": _short(result),
            "next": next_step,
            "why": why,
            "phase": phase,
            "step_kind": step_kind or ("llm" if extra.get("model") else "human" if agent_name == "human" else "code"),
            "message": message or _message(action, decision, why),
            **({"payload": payload} if payload is not None else {}),
            **({"terminal": True} if terminal else {}),
            **{k: _short(v) for k, v in extra.items() if v is not None},
        }
        line = mask(json.dumps(event, ensure_ascii=False))
        self.events.append(json.loads(line))
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

        model = f" model={extra['model']}" if extra.get("model") else ""
        text = f"run={self.run_id} agent={agent_name} action={action}{model} -> {decision}"
        if next_step:
            text += f" (next: {next_step})"
        logger.log(level, mask(text))

    def error(self, agent_name: str, action: str, exc: BaseException, next_step: str, terminal: bool = False) -> None:
        """terminal=True when the flow ends with this error (it is raised to the caller)."""
        self.log(
            agent_name, action, "error", next_step=next_step, why="exception raised",
            level=logging.ERROR, error={"type": type(exc).__name__, "message": str(exc)},
            phase="error", message=f"{action} failed: {type(exc).__name__}", terminal=terminal,
        )


def mask(text: str) -> str:
    for name in SECRET_ENV_VARS:
        value = os.getenv(name)
        if value and len(value) >= 4:
            text = text.replace(value, "***")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda m: m.group(1) + "***", text)
    return text


def _message(action: str, decision: str, why: str, limit: int = 300) -> str:
    text = f"{action}: {decision}" + (f". {why}" if why else "")
    return text if len(text) <= limit else text[:limit] + "..."


def _short(value: Any, limit: int = 500) -> Any:
    """Keep log lines readable: summarise lists and long text."""
    if isinstance(value, list):
        return f"{len(value)} items"
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "..."
    if hasattr(value, "model_dump"):
        return _short(json.dumps(value.model_dump(mode="json"), ensure_ascii=False), limit)
    return value
