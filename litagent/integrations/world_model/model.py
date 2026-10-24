"""World Model facade: event-sourced, deterministic, single-writer (a lock serializes writes).

Python port of engines/world-model/reference/src/index.ts (Meterless, Apache-2.0), with snake_case
names. Every write carries provenance ({"kind", "at"} at minimum); no provenance, no write.
"""

from __future__ import annotations

import copy
import threading
import time
from datetime import datetime
from typing import Any, Callable, Literal

from litagent.integrations.world_model.ingest import run_ingest_pipeline, world_state_shape
from litagent.integrations.world_model.resolve import AUTO_MERGE_AT, REVIEW_LOWER, decide, normalized_similarity
from litagent.integrations.world_model.stable_ids import (
    canonical_json, context_id_from_attrs, entity_id_from_name, external_id, fact_id, iso, normalize_name, relationship_id,
)
from litagent.integrations.world_model.store import EventStore, Storage

ConflictPolicy = Literal["most-recent-wins", "highest-confidence-wins", "source-priority"]


class WorldModelError(ValueError):
    pass


class WorldModel:
    def __init__(
        self,
        namespace: str,
        storage: Storage = "memory",
        directory: str | None = None,
        clock: Callable[[], datetime] | None = None,
        conflict_policy: ConflictPolicy = "most-recent-wins",
        source_priority: list[str] | None = None,
        auto_merge_at: float = AUTO_MERGE_AT,
        review_lower: float = REVIEW_LOWER,
        multi_valued_types: set[str] | None = None,
        resolver_bands: dict[str, tuple[float, float]] | None = None,
    ):
        """`multi_valued_types`: edge types that keep several current targets (spec §6.1, typed graph:
        each edge type has its own constraints). Other types follow the reference: a new target
        supersedes the old one, which is what makes bitemporal queries work.

        `resolver_bands`: per entity type (auto_merge_at, review_lower), overriding the defaults for
        types whose names collide easily. With auto_merge_at above 1, near-matches of that type are
        only ever queued for review (spec §7.1: merge proposals are never auto-destructive)."""
        if not namespace:
            raise WorldModelError("WorldModel: namespace is required")
        self.store = EventStore(namespace, storage, directory, frozenset(multi_valued_types or ()))
        self.clock = clock or (lambda: datetime.now().astimezone())
        self.conflict_policy = conflict_policy
        self.source_priority = source_priority or []
        self.auto_merge_at, self.review_lower = auto_merge_at, review_lower
        self.resolver_bands = resolver_bands or {}
        self._lock = threading.RLock()
        self._custom_views: dict[str, dict] = {}
        self._normalized: dict[str, str] = {}  # entity id -> normalized name, for resolution

    # ------------------------------------------------------------------ writes

    @staticmethod
    def _provenance(source: dict | None) -> dict:
        if not source or not source.get("kind") or source.get("at") is None:
            raise WorldModelError("World Model: every write carries provenance (kind + at). No provenance, no write.")
        at = source["at"]
        return {**source, "at": iso(at) if isinstance(at, datetime) else at}

    def upsert_entity(self, type: str, source: dict, name: str | None = None, external_key: dict | None = None,
                      attrs: dict | None = None, state: str | None = None) -> dict:
        with self._lock:
            src = self._provenance(source)
            name = name or (attrs or {}).get("name")
            if external_key:
                id_ = external_id(type, external_key["system"], external_key["id"])
            elif name:
                id_ = entity_id_from_name(type, name)
            else:
                raise WorldModelError("World Model: name-keyed entities need a name (or provide an external_key)")

            # Resolution for name-keyed entities: near-duplicates of the same type either auto-merge
            # (alias event) or queue for operator review. An entity that already exists was resolved
            # when it was first written, so re-upserting it skips the scan.
            if not external_key and name and id_ not in self.store.state.entities:
                norm = normalize_name(name)
                auto_merge_at, review_lower = self.resolver_bands.get(type, (self.auto_merge_at, self.review_lower))
                for other in list(self.store.state.entities.values()):
                    if other["type"] != type or other["id"] == id_ or not other.get("name"):
                        continue
                    similarity = normalized_similarity(norm, self._normalized_name(other), floor=review_lower)
                    verdict = decide(similarity, auto_merge_at, review_lower)
                    if verdict == "auto-merge":
                        self.store.append("alias", {"aliasId": id_, "primaryId": other["id"], "mergedAt": src["at"],
                                                    "mergedBy": "resolver", "reason": f"similarity {similarity:.3f}"}, src["at"])
                        self.store.log_audit("auto-merge", "resolver", f"{name} -> {other['name']} ({similarity:.3f})", at=src["at"])
                        return self._fold_entity_upsert(other["id"], type, src, name, attrs, state)
                    if verdict == "review" and not any(
                        {p["leftId"], p["rightId"]} == {id_, other["id"]} for p in self.store.merge_queue
                    ):
                        self.store.merge_queue.append({
                            "id": f"merge_{len(self.store.merge_queue) + 1}", "leftId": id_, "rightId": other["id"],
                            "leftName": name, "rightName": other["name"], "similarity": similarity,
                            "reason": f"name similarity in review band [{review_lower}, {auto_merge_at})",
                            "status": "pending", "proposedAt": src["at"],
                        })
                        self.store.log_audit("merge-proposed", "resolver",
                                             f"{name} ~ {other['name']} ({similarity:.3f}) queued", at=src["at"])
            return self._fold_entity_upsert(id_, type, src, name, attrs, state)

    def _fold_entity_upsert(self, id_: str, type: str, src: dict, name: str | None, attrs: dict | None,
                            state: str | None) -> dict:
        resolved = self.store.resolve_alias(id_)
        entity: dict[str, Any] = {
            "type": type, "id": resolved, "attrs": dict(attrs or {}), "schemaVersion": 1, "source": src,
            "createdAt": src["at"], "updatedAt": src["at"], "aliases": [name] if name else [], "state": state or "active",
        }
        if name:
            entity["name"] = name
        event = self.store.append("upsertEntity", entity, src["at"])
        self.store.log_audit("upsertEntity", src.get("by", "system"), f"{resolved} ({type})", event["id"], src.get("runId"), src["at"])
        current = self.store.state.entities[resolved]
        self._normalized.pop(resolved, None)  # its name may have changed
        return current

    def _normalized_name(self, entity: dict) -> str:
        if entity["id"] not in self._normalized:
            self._normalized[entity["id"]] = normalize_name(entity["name"])
        return self._normalized[entity["id"]]

    def upsert_context(self, type: str, source: dict, external_key: dict | None = None, attrs: dict | None = None,
                       parent: str | None = None) -> dict:
        with self._lock:
            src = self._provenance(source)
            id_ = (external_id(type, external_key["system"], external_key["id"]) if external_key
                   else context_id_from_attrs(type, attrs or {}, parent))
            context: dict[str, Any] = {"type": type, "id": id_, "attrs": dict(attrs or {}), "schemaVersion": 1,
                                       "source": src, "createdAt": src["at"], "updatedAt": src["at"]}
            if parent:
                context["parent"] = parent
            event = self.store.append("upsertContext", context, src["at"])
            self.store.log_audit("upsertContext", src.get("by", "system"), f"{id_} ({type})", event["id"], src.get("runId"), src["at"])
            return self.store.state.contexts[id_]

    def relate(self, from_id: str, type: str, to_id: str, source: dict, context: str | None = None,
               attrs: dict | None = None, valid_from: str | None = None, valid_to: str | None = None) -> dict:
        with self._lock:
            src = self._provenance(source)
            frm, to = self.store.resolve_alias(from_id), self.store.resolve_alias(to_id)
            id_ = relationship_id(frm, type, to, context, valid_from)
            if id_ in self.store.state.relationships:
                return self.store.state.relationships[id_]  # content-addressed no-op
            rel: dict[str, Any] = {"id": id_, "from": frm, "type": type, "to": to, "validFrom": valid_from or src["at"],
                                   "schemaVersion": 1, "source": src, "createdAt": src["at"]}
            for key, value in (("context", context), ("attrs", attrs), ("validTo", valid_to)):
                if value is not None:
                    rel[key] = value
            event = self.store.append("relate", rel, src["at"])
            self.store.log_audit("relate", src.get("by", "system"), f"{frm} -[{type}]-> {to}", event["id"], src.get("runId"), src["at"])
            return self.store.state.relationships[id_]

    def assert_fact(self, about: str, predicate: str, value: Any, source: dict, confidence: float = 0.5,
                    context: str | None = None) -> dict:
        with self._lock:
            src = self._provenance(source)
            about = self.store.resolve_alias(about)
            id_ = fact_id(about, predicate, value, src["at"], src["kind"], src.get("url"))
            if id_ in self.store.state.facts:
                return self.store.state.facts[id_]
            fact: dict[str, Any] = {"id": id_, "about": about, "predicate": predicate, "value": value,
                                    "confidence": confidence, "source": src, "assertedAt": src["at"]}
            if context:
                fact["context"] = context

            # The conflict policy decides which fact's value lands on the entity.
            rivals = [f for f in self.store.state.facts.values()
                      if f["about"] == about and f["predicate"] == predicate and not f.get("supersededBy")]
            winner = fact
            for rival in rivals:
                if self._rival_wins(rival, winner):
                    winner = rival
            event = self.store.append("assertFact", fact, src["at"])
            for f in [fact, *rivals]:
                if f["id"] != winner["id"]:
                    self.store.state.facts[f["id"]]["supersededBy"] = winner["id"]

            if about not in self.store.state.entities:  # the subject must exist
                inferred = about.split(":")[0] if ":" in about else "entity"
                self.store.append("upsertEntity", {"type": inferred, "id": about, "attrs": {}, "schemaVersion": 1,
                                                   "source": src, "createdAt": src["at"], "updatedAt": src["at"],
                                                   "aliases": [], "state": "emerging"}, src["at"])
            entity = self.store.state.entities[about]
            entity["attrs"][predicate] = winner["value"]
            entity["updatedAt"] = src["at"]
            self.store.log_audit("assertFact", src.get("by", "system"),
                                 f"{about}.{predicate} = {canonical_json(winner['value'])} ({self.conflict_policy})",
                                 event["id"], src.get("runId"), src["at"])
            return self.store.state.facts[id_]

    def _rival_wins(self, rival: dict, winner: dict) -> bool:
        if self.conflict_policy == "highest-confidence-wins":
            return rival["confidence"] > winner["confidence"]
        if self.conflict_policy == "source-priority":
            return self._priority(rival["source"]["kind"]) < self._priority(winner["source"]["kind"])
        return rival["assertedAt"] > winner["assertedAt"]

    def _priority(self, kind: str) -> int:
        return self.source_priority.index(kind) if kind in self.source_priority else 1_000_000

    # ------------------------------------------------------------------ ingest

    def ingest(self, observations: list[dict]) -> dict:
        with self._lock:
            def upsert(obs: dict) -> tuple[str, list[str]]:
                src = self._provenance({**obs["source"], "at": obs["at"]})
                type_ = obs.get("type", "item")
                entity = self._fold_entity_upsert(external_id(type_, "ingest", obs["externalId"]), type_, src,
                                                  obs["title"], {"title": obs["title"], "text": obs.get("text")}, None)
                mentioned: list[str] = []
                for mention in obs.get("entities", []):
                    mid = entity_id_from_name(mention["type"], mention["name"])
                    self._fold_entity_upsert(mid, mention["type"], src, mention["name"], None, None)
                    target = self.store.resolve_alias(mid)
                    mentioned.append(target)
                    rid = relationship_id(entity["id"], "mentions", target)
                    if rid not in self.store.state.relationships:
                        self.store.append("relate", {"id": rid, "from": entity["id"], "type": "mentions", "to": target,
                                                     "validFrom": src["at"], "schemaVersion": 1, "source": src,
                                                     "createdAt": src["at"]}, src["at"])
                return entity["id"], sorted(mentioned)

            return run_ingest_pipeline(self.store, observations, upsert, lambda: time.monotonic() * 1000)

    # ------------------------------------------------------------------ reads

    def view(self, name: str) -> Any:
        if name == "graph":
            return GraphView(self.store)
        if name == "facts":
            return FactsView(self.store)
        if name == "snapshot":
            return SnapshotView(self.store)
        if name == "timeline":
            return TimelineView(self.store)
        if name not in self._custom_views:
            raise WorldModelError(f'World Model: unknown view "{name}"')
        spec = self._custom_views[name]
        state = copy.deepcopy(spec["initial_state"])
        for event in self.store.events:
            if event["kind"] in spec["events"]:
                state = spec["reducer"](state, event)
        return state

    def register_view(self, name: str, events: list[str], initial_state: Any, reducer: Callable[[Any, dict], Any]) -> None:
        self._custom_views[name] = {"events": events, "initial_state": initial_state, "reducer": reducer}

    # ------------------------------------------------------------------ operator

    def merge_queue(self) -> list[dict]:
        return self.store.merge_queue

    def approve_merge(self, proposal_id: str, by: str) -> None:
        with self._lock:
            p = self._pending(proposal_id)
            at = iso(self.clock())
            p.update(status="approved", resolvedAt=at, resolvedBy=by)
            self.store.append("alias", {"aliasId": p["leftId"], "primaryId": p["rightId"], "mergedAt": at,
                                        "mergedBy": by, "reason": p["reason"]}, at)
            self.store.log_audit("merge-approved", by, f"{p['leftName']} -> {p['rightName']}", at=at)

    def reject_merge(self, proposal_id: str, by: str) -> None:
        with self._lock:
            p = self._pending(proposal_id)
            at = iso(self.clock())
            p.update(status="rejected", resolvedAt=at, resolvedBy=by)
            self.store.log_audit("merge-rejected", by, f"{p['leftName']} stays separate from {p['rightName']}", at=at)

    def _pending(self, proposal_id: str) -> dict:
        for p in self.store.merge_queue:
            if p["id"] == proposal_id and p["status"] == "pending":
                return p
        raise WorldModelError(f"World Model: no pending merge proposal {proposal_id}")

    def audit(self) -> list[dict]:
        return self.store.audit

    def events(self) -> list[dict]:
        return self.store.events

    def state_shape(self) -> dict:
        return world_state_shape(self.store)

    def state_shape_canonical(self) -> str:
        return canonical_json(world_state_shape(self.store))

    def subscribe_events(self, fn: Callable[[dict], None]) -> Callable[[], None]:
        return self.store.subscribe(fn)

    def flush(self) -> None:
        with self._lock:
            self.store.flush()


# ---------------------------------------------------------------------- views


class GraphView:
    def __init__(self, store: EventStore):
        self.store = store

    def entity(self, id_: str) -> dict | None:
        return self.store.state.entities.get(self.store.resolve_alias(id_))

    def neighbors_of(self, id_: str, via: str | None = None, in_context: str | None = None, at: str | None = None) -> list[dict]:
        rid = self.store.resolve_alias(id_)
        out = []
        for rel in self.store.state.relationships.values():
            if via and rel["type"] != via:
                continue
            if in_context and rel.get("context") != in_context:
                continue
            if at and not valid_at(rel, at):
                continue
            if not at and rel.get("validTo"):
                continue  # closed edges are excluded from "now" queries
            other = rel["to"] if rel["from"] == rid else rel["from"] if rel["to"] == rid else None
            if other and other in self.store.state.entities:
                out.append(self.store.state.entities[other])
        return sorted(out, key=lambda e: e["id"])

    def incoming(self, id_: str, via: str | None = None, in_context: str | None = None) -> list[dict]:
        rid = self.store.resolve_alias(id_)
        out = [self.store.state.entities[r["from"]] for r in self.store.state.relationships.values()
               if r["to"] == rid and (not via or r["type"] == via) and not r.get("validTo")
               and (not in_context or r.get("context") == in_context) and r["from"] in self.store.state.entities]
        return sorted(out, key=lambda e: e["id"])

    def relationships(self, type: str | None = None, in_context: str | None = None, at: str | None = None) -> list[dict]:
        """Open relationships (or those valid at `at`), optionally of one type and in one context."""
        return sorted(
            (r for r in self.store.state.relationships.values()
             if (not type or r["type"] == type) and (not in_context or r.get("context") == in_context)
             and (valid_at(r, at) if at else not r.get("validTo"))),
            key=lambda r: r["id"],
        )

    def entities_in_context(self, context_id: str, type: str | None = None) -> list[dict]:
        seen: dict[str, dict] = {}
        for rel in self.store.state.relationships.values():
            if rel.get("context") != context_id:
                continue
            for id_ in (rel["from"], rel["to"]):
                entity = self.store.state.entities.get(id_)
                if entity and (not type or entity["type"] == type):
                    seen[entity["id"]] = entity
        return sorted(seen.values(), key=lambda e: e["id"])

    def traverse(self, start_id: str, via: str, direction: Literal["ancestors", "descendants"], max_depth: int = 5) -> list[dict]:
        out, visited = [], set()
        frontier = [self.store.resolve_alias(start_id)]
        for _ in range(max_depth):
            if not frontier:
                break
            nxt = []
            for id_ in frontier:
                for rel in self.store.state.relationships.values():
                    if rel["type"] != via or rel.get("validTo"):
                        continue
                    target = (rel["to"] if rel["from"] == id_ else None) if direction == "ancestors" else (
                        rel["from"] if rel["to"] == id_ else None)
                    if target and target not in visited:
                        visited.add(target)
                        if target in self.store.state.entities:
                            out.append(self.store.state.entities[target])
                        nxt.append(target)
            frontier = nxt
        return out

    def query(self, type: str | None = None, where: Callable[[dict], bool] | None = None) -> list[dict]:
        return sorted((e for e in self.store.state.entities.values()
                       if (not type or e["type"] == type) and (not where or where(e))), key=lambda e: e["id"])


class FactsView:
    def __init__(self, store: EventStore):
        self.store = store

    def about(self, id_: str) -> list[dict]:
        rid = self.store.resolve_alias(id_)
        return sorted((f for f in self.store.state.facts.values() if f["about"] == rid), key=lambda f: f["assertedAt"])


class SnapshotView:
    def __init__(self, store: EventStore):
        self.store = store

    def entity_at(self, id_: str, at: str) -> dict | None:
        """Entity state as of a timestamp: replay events with at <= timestamp."""
        state = self.store.fold_until(f"{at}T23:59:59.999Z" if len(at) == 10 else at)
        cur, seen = id_, set()
        while cur in state.aliases and cur not in seen:
            seen.add(cur)
            cur = state.aliases[cur]
        return state.entities.get(cur)


class TimelineView:
    def __init__(self, store: EventStore):
        self.store = store

    def get(self) -> list[dict]:
        return list(self.store.events)

    def subscribe(self, fn: Callable[[dict], None]) -> Callable[[], None]:
        return self.store.subscribe(fn)


def valid_at(rel: dict, at: str) -> bool:
    if rel.get("validFrom") and at < rel["validFrom"]:
        return False
    if rel.get("validTo") and at >= rel["validTo"]:
        return False
    return True
