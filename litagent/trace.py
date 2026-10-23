"""Run log: one JSON line per step (step, decision, result, next, why).

Judges reward traces that show how the agent got its answer, so log from day one.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class Trace:
    def __init__(self, runs_dir: str = "runs", run_id: str | None = None):
        self.run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        self.path = Path(runs_dir) / f"{self.run_id}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.events: list[dict[str, Any]] = []

    def log(self, agent: str, step: str, decision: str, result: Any = None, next_step: str = "", why: str = "") -> None:
        event = {
            "time": datetime.now(timezone.utc).isoformat(),
            "agent": agent,
            "step": step,
            "decision": decision,
            "result": _short(result),
            "next": next_step,
            "why": why,
        }
        self.events.append(event)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _short(value: Any, limit: int = 500) -> Any:
    """Keep log lines readable: summarise lists and long text."""
    if isinstance(value, list):
        return f"{len(value)} items"
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "..."
    if hasattr(value, "model_dump"):
        return _short(json.dumps(value.model_dump(mode="json"), ensure_ascii=False), limit)
    return value
