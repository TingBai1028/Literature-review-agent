"""Event-sourced canonical store. State is a fold over an append-only event log; views are
projections of the fold. Every mutation writes an audit entry.

Persistence ("local" storage) is one JSON file per namespace, replayed on load. Unlike the
reference, which rewrites the file on every append, writes are batched (spec §3.4: debounce writes):
callers flush() at the end of a stage.

Python port of engines/world-model/reference/src/store.ts (Meterless, Apache-2.0).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Callable, Literal

Storage = Literal["memory", "local"]


class FoldedState:
    def __init__(self) -> None:
        self.entities: dict[str, dict] = {}
        self.contexts: dict[str, dict] = {}
        self.relationships: dict[str, dict] = {}
        self.facts: dict[str, dict] = {}
        self.aliases: dict[str, str] = {}  # alias id -> primary id


class EventStore:
    def __init__(self, namespace: str, storage: Storage = "memory", directory: str | None = None,
                 multi_valued_types: frozenset[str] = frozenset()):
        # Edge types that may have several current targets (a paper's authors). All other types are
        # functional, as in the reference: a new target closes the previous edge.
        self.multi_valued_types = multi_valued_types
        self.events: list[dict] = []
        self.audit: list[dict] = []
        self.observations: dict[str, dict] = {}
        self.stories: dict[str, dict] = {}
        self.scores: list[dict] = []
        self.merge_queue: list[dict] = []
        self.state = FoldedState()
        self._seq = 0
        self._audit_seq = 0
        self._subscribers: list[Callable[[dict], None]] = []
        self._dirty = False
        self.file: Path | None = None
        if storage == "local":
            self.file = Path(directory or ".") / f"world-{namespace}.json"
            if self.file.exists():
                self._load(json.loads(self.file.read_text(encoding="utf-8")))

    def _load(self, saved: dict) -> None:
        self.audit = saved.get("audit", [])
        self._audit_seq = self.audit[-1]["seq"] if self.audit else 0
        self.observations = dict(saved.get("observations", []))
        self.stories = dict(saved.get("stories", []))
        self.scores = saved.get("scores", [])
        self.merge_queue = saved.get("mergeQueue", [])
        for event in saved.get("events", []):
            self._seq = max(self._seq, event["seq"])
            self.events.append(event)
            self.fold(event)

    def append(self, kind: str, payload: dict, at: str) -> dict:
        self._seq += 1
        event = {"id": f"evt_{self._seq}", "seq": self._seq, "kind": kind, "payload": payload, "schemaVersion": 1, "at": at}
        self.events.append(event)
        self.fold(event)
        self._dirty = True
        for fn in self._subscribers:
            fn(event)
        return event

    def fold(self, event: dict) -> None:
        kind, p = event["kind"], event["payload"]
        s = self.state
        if kind == "upsertEntity":
            existing = s.entities.get(p["id"])
            if existing:
                existing["attrs"] = {**existing["attrs"], **p["attrs"]}
                existing["updatedAt"] = p["updatedAt"]
                existing["source"] = p["source"]
                if p.get("name"):
                    if p["name"] not in existing["aliases"]:
                        existing["aliases"].append(p["name"])
                    existing["name"] = p["name"]
            else:
                s.entities[p["id"]] = copy.deepcopy(p)
        elif kind == "upsertContext":
            existing = s.contexts.get(p["id"])
            if existing:
                existing["attrs"] = {**existing["attrs"], **p["attrs"]}
                existing["updatedAt"] = p["updatedAt"]
            else:
                s.contexts[p["id"]] = copy.deepcopy(p)
        elif kind == "relate":
            # Superseding: a new open edge with the same (from, type, context) but a different target
            # closes the previous open edge, unless the type is multi-valued.
            for other in ([] if p["type"] in self.multi_valued_types else s.relationships.values()):
                if (other["from"] == p["from"] and other["type"] == p["type"]
                        and other.get("context", "") == p.get("context", "") and other["to"] != p["to"]
                        and not other.get("validTo") and not other.get("supersededBy")):
                    other["validTo"] = p.get("validFrom") or p["createdAt"]
                    other["supersededBy"] = p["id"]
            if p["id"] not in s.relationships:
                s.relationships[p["id"]] = copy.deepcopy(p)
        elif kind == "assertFact":
            if p["id"] not in s.facts:
                s.facts[p["id"]] = copy.deepcopy(p)
        elif kind == "alias":
            s.aliases[p["aliasId"]] = p["primaryId"]
        # "snapshot", "tombstone" and "view-rebuild" events change no folded state

    def fold_until(self, at: str) -> FoldedState:
        """Replay the event log up to and including a timestamp: the snapshot view."""
        scratch = EventStore("scratch", multi_valued_types=self.multi_valued_types)
        for event in self.events:
            if event["at"] <= at:
                scratch.fold(event)
        return scratch.state

    def resolve_alias(self, id_: str) -> str:
        cur, seen = id_, set()
        while cur in self.state.aliases and cur not in seen:
            seen.add(cur)
            cur = self.state.aliases[cur]
        return cur

    def log_audit(self, kind: str, actor: str, summary: str, event_id: str | None = None,
                  run_id: str | None = None, at: str | None = None) -> None:
        self._audit_seq += 1
        entry: dict[str, Any] = {"seq": self._audit_seq, "at": at or "1970-01-01T00:00:00.000Z",
                                 "kind": kind, "actor": actor, "summary": summary}
        if event_id:
            entry["eventId"] = event_id
        if run_id:
            entry["runId"] = run_id
        self.audit.append(entry)
        self._dirty = True

    def subscribe(self, fn: Callable[[dict], None]) -> Callable[[], None]:
        self._subscribers.append(fn)
        return lambda: self._subscribers.remove(fn)

    def flush(self) -> None:
        """Write the event log to disk if anything changed since the last flush."""
        if not self.file or not self._dirty:
            return
        data = {
            "events": self.events,
            "audit": self.audit,
            "observations": list(self.observations.items()),
            "stories": list(self.stories.items()),
            "scores": self.scores,
            "mergeQueue": self.merge_queue,
        }
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tmp.replace(self.file)  # atomic: a crash mid-write never leaves a half-written world
        self._dirty = False
