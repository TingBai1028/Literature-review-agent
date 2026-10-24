"""The canonical ingest pipeline (spec: AGENTS.md §4.1). Idempotency contract: re-running the same
batch produces the same world state and reports changed=False. Every derived timestamp comes from
the observation, never the wall clock.

Python port of engines/world-model/reference/src/ingest.ts (Meterless, Apache-2.0).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from litagent.integrations.world_model.resolve import jaccard
from litagent.integrations.world_model.stable_ids import canonical_json, iso, sha256_hex
from litagent.integrations.world_model.store import EventStore

CLUSTER_JACCARD = 0.5
HOUR = timedelta(hours=1)


def run_ingest_pipeline(
    store: EventStore,
    observations: list[dict],
    upsert: Callable[[dict], tuple[str, list[str]]],
    timer: Callable[[], float],
) -> dict:
    """`upsert(observation)` writes the observation's entity and mentions; returns (entity id, mentioned ids)."""
    run_id = "run_" + sha256_hex(canonical_json([o["externalId"] for o in observations]))[:12]
    timings: list[dict] = []
    before = canonical_json(world_state_shape(store))
    events_before = len(store.events)

    def timed(step: int, name: str, fn: Callable[[], object]) -> object:
        t0 = timer()
        out = fn()
        timings.append({"step": step, "name": name, "ms": timer() - t0})
        return out

    # 1. Reconcile: recompute staleness from observation times (30 days before the newest).
    def reconcile() -> None:
        latest = max((o["at"] for o in observations), default="")
        for rec in store.observations.values():
            rec["stale"] = latest != "" and rec["at"] < iso(_parse(latest) - timedelta(days=30))
    timed(1, "reconcile-stale", reconcile)

    # 2. Classify: unchanged observations (same checksum) are skipped.
    fresh: list[tuple[dict, str]] = []
    skipped: list[dict] = []

    def classify() -> None:
        for obs in observations:
            checksum = sha256_hex(canonical_json({"externalId": obs["externalId"], "title": obs["title"],
                                                  "text": obs.get("text") or "", "at": obs["at"]}))
            existing = store.observations.get(obs["externalId"])
            if existing and existing["checksum"] == checksum:
                skipped.append(obs)
            else:
                fresh.append((obs, checksum))
    timed(2, "cluster-classify", classify)

    # 3. Persist primary aggregates: observation entities and their mentions (edges written by `upsert`).
    def persist() -> None:
        for obs, checksum in fresh:
            entity_id, entity_ids = upsert(obs)
            store.observations[obs["externalId"]] = {
                "id": "obs_" + sha256_hex(obs["externalId"])[:12], "externalId": obs["externalId"],
                "entityId": entity_id, "checksum": checksum, "at": obs["at"], "entityIds": entity_ids, "stale": False,
            }
    timed(3, "persist-aggregates", persist)

    # Group observations into stories by entity overlap.
    clusters: list[list[dict]] = []

    def group() -> None:
        records = sorted(store.observations.values(), key=lambda r: r["externalId"])
        used: set[str] = set()
        for seed in records:
            if seed["externalId"] in used:
                continue
            members = [seed]
            used.add(seed["externalId"])
            for other in records:
                if other["externalId"] not in used and jaccard(seed.get("entityIds", []), other.get("entityIds", [])) >= CLUSTER_JACCARD:
                    members.append(other)
                    used.add(other["externalId"])
            clusters.append(members)
    timed(2, "story-grouping", group)

    # 4. Score: velocity = mentions per hour over bucketed windows ending at the newest observation.
    #    5-8: derived records, mention edges (in `upsert`), views (projected on read), patching items.
    def score() -> None:
        for members in clusters:
            member_ids = sorted(m["externalId"] for m in members)
            story_id = "story_" + sha256_hex(canonical_json(member_ids))[:12]
            times = sorted(_parse(m["at"]) for m in members)
            last = times[-1]

            def velocity(window: timedelta) -> float:
                return sum(1 for t in times if t > last - window) / (window / HOUR)

            prev_hour = sum(1 for t in times if last - 2 * HOUR < t <= last - HOUR)
            curr_hour = sum(1 for t in times if t > last - HOUR)
            store.scores = [s for s in store.scores if s["storyId"] != story_id]
            store.scores.append({
                "storyId": story_id, "at": iso(last), "velocity1h": velocity(HOUR),
                "velocity24h": velocity(24 * HOUR), "velocity7d": velocity(7 * 24 * HOUR),
                "trendDirection": (curr_hour > prev_hour) - (curr_hour < prev_hour),
            })
            entity_ids = sorted({e for m in members for e in m.get("entityIds", [])})
            store.stories[story_id] = {
                "id": story_id, "title": members[0]["externalId"], "memberIds": member_ids,
                "entityNames": entity_ids, "entityIds": entity_ids, "sources": [],
                "firstAt": iso(times[0]), "lastAt": iso(last),
                "milestones": [{"kind": "multi-source", "at": iso(times[1])}] if len(members) >= 2 else [],
            }
            for m in members:
                m["storyId"] = story_id  # step 8: patch source items
    timed(4, "score-measure", score)

    # 9. Rebuild aggregates: mention counts and first/last seen, recomputed (never incremented).
    def rebuild() -> None:
        for entity in store.state.entities.values():
            mentions = [o for o in store.observations.values() if entity["id"] in o.get("entityIds", [])]
            if not mentions:
                continue
            times = sorted(m["at"] for m in mentions)
            entity["aggregates"] = {
                "mentionCount": len(mentions), "firstSeenAt": times[0], "lastSeenAt": times[-1],
                "linkedStoryIds": sorted({m["storyId"] for m in mentions if m.get("storyId")}),
            }
    timed(9, "rebuild-aggregates", rebuild)

    after = canonical_json(world_state_shape(store))
    store.log_audit("ingest", "pipeline", f"run {run_id}: {len(fresh)} processed, {len(skipped)} skipped",
                    run_id=run_id, at=observations[0]["at"] if observations else None)
    return {
        "runId": run_id, "processed": len(fresh), "skippedUnchanged": len(skipped), "clusters": len(clusters),
        "eventsAppended": len(store.events) - events_before, "changed": before != after, "stepTimingsMs": timings,
    }


def world_state_shape(store: EventStore) -> dict:
    """The idempotency diff surface: everything derived from observations, in canonical order."""
    return {
        "entities": sorted(store.state.entities.values(), key=lambda e: e["id"]),
        "contexts": sorted(store.state.contexts.values(), key=lambda c: c["id"]),
        "relationships": sorted(store.state.relationships.values(), key=lambda r: r["id"]),
        "facts": sorted(store.state.facts.values(), key=lambda f: f["id"]),
        "observations": sorted(store.observations.values(), key=lambda o: o["externalId"]),
        "stories": sorted(store.stories.values(), key=lambda s: s["id"]),
    }


def _parse(at: str) -> datetime:
    return datetime.fromisoformat(at.replace("Z", "+00:00"))
