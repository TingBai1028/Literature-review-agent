"""Live progress events (spec A1, B3): the run's trace file served as a server-sent event stream.

Every trace line is one event, so the map animation, the activity feed and the reasoning panel all read the
same log. The client picks the run ID, subscribes to GET /runs/{run_id}/events, then starts the run with that
ID; events already written are replayed first. Spec: docs/events.md
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import AsyncIterator


def to_event(seq: int, record: dict) -> dict:
    """One trace line in the A1 event shape, plus the B3 run-log fields (step, decision, result, next, why)."""
    return {"run_id": record["run_id"], "seq": seq, "ts": record["timestamp"], "agent": record["agent_name"],
            "phase": record.get("phase", "error" if record.get("decision") == "error" else "step"),
            "message": record.get("message") or f"{record['action']}: {record['decision']}",
            "payload": record.get("payload"), "step": record["action"], "step_kind": record.get("step_kind"),
            "decision": record["decision"], "result": record.get("result"), "next": record.get("next", ""),
            "why": record.get("why", ""), "terminal": bool(record.get("terminal"))}


def read_events(path: Path, after: int = -1) -> list[dict]:
    """Events already written, for clients that poll instead of streaming."""
    if not path.exists():
        return []
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [to_event(seq, json.loads(line)) for seq, line in enumerate(lines) if seq > after]


def _sse(event: dict) -> str:
    return f"id: {event['seq']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


async def stream_events(path: Path, run_id: str, after: int = -1, *, wait_s: float = 60, max_s: float = 900,
                        poll_s: float = 0.25) -> AsyncIterator[str]:
    """Yield events as the trace file grows; stop after the run's terminal event, or when the run never starts
    (wait_s) or runs past max_s. Only complete lines are sent."""
    started, offset, seq, buffer = time.monotonic(), 0, -1, b""
    while True:
        if path.exists():
            with path.open("rb") as f:
                f.seek(offset)
                chunk = f.read()
            offset += len(chunk)
            *lines, buffer = (buffer + chunk).split(b"\n")
            for line in lines:
                if not line.strip():
                    continue
                seq += 1
                if seq <= after:
                    continue
                event = to_event(seq, json.loads(line))
                yield _sse(event)
                if event["terminal"]:
                    return
        elif time.monotonic() - started > wait_s:
            yield _sse({"run_id": run_id, "seq": -1, "ts": None, "agent": "orchestrator", "phase": "error",
                        "message": f"No run with ID {run_id} started within {wait_s:.0f} s.", "payload": None,
                        "terminal": True})
            return
        if time.monotonic() - started > max_s:
            yield _sse({"run_id": run_id, "seq": seq + 1, "ts": None, "agent": "orchestrator", "phase": "error",
                        "message": "The event stream reached its time limit; reload the map for the final result.",
                        "payload": None, "terminal": True})
            return
        await asyncio.sleep(poll_s)
