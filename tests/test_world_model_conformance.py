"""Meterless World Model conformance, ported check for check from the spec's suite
(engines/world-model/conformance/runner.ts, https://github.com/Meterless/Meterless).
"An implementation is done when this suite is green."

The parity section pins values computed by Meterless's TypeScript reference implementation
(npx tsx, 24 Oct 2026), so our Python port must produce exactly the same IDs and decisions.
"""

from datetime import datetime, timezone

import pytest

from litagent.integrations.world_model import WorldModel, WorldModelError, decide, entity_id_from_name, normalize_name
from litagent.integrations.world_model.resolve import name_similarity
from litagent.integrations.world_model.stable_ids import (
    canonical_json, context_id_from_attrs, external_id, fact_id, relationship_id,
)

OBSERVATIONS = [
    {"externalId": "a1", "title": "Fed holds rates", "at": "2026-05-17T14:00:00.000Z",
     "source": {"kind": "rss", "at": "2026-05-17T14:00:00.000Z"}, "entities": [{"type": "person", "name": "Jerome Powell"}]},
    {"externalId": "a2", "title": "Powell signals patience", "at": "2026-05-17T16:30:00.000Z",
     "source": {"kind": "rss", "at": "2026-05-17T16:30:00.000Z"}, "entities": [{"type": "person", "name": "Jerome Powell"}]},
]


def clock():
    return datetime(2026, 5, 18, tzinfo=timezone.utc)


# ----- the 8 conformance checks -----

def test_sid_001_diacritics_and_nbsp_normalize_identically():
    assert normalize_name("José  García") == normalize_name("Jose Garcia")
    assert entity_id_from_name("person", "José García") == entity_id_from_name("person", "jose garcia")


def test_sid_002_distinct_names_stay_distinct():
    assert entity_id_from_name("org", "Acme Corp") != entity_id_from_name("org", "Acme Corporation")
    assert entity_id_from_name("person", "x") != entity_id_from_name("org", "x")


def test_band_001_merge_bands_at_the_boundaries():
    assert decide(0.85) == "auto-merge"
    assert decide(0.84) == "review"
    assert decide(0.82) == "review"
    assert decide(0.81) == "new"


def test_prov_001_writes_without_provenance_are_rejected():
    world = WorldModel("conf")
    with pytest.raises(WorldModelError, match="No provenance, no write"):
        world.upsert_entity(type="person", name="No Provenance", source=None)


def test_idem_001_same_batch_twice_produces_an_empty_diff():
    world = WorldModel("conf", clock=clock)
    world.ingest(OBSERVATIONS)
    shape = world.state_shape_canonical()
    second = world.ingest(OBSERVATIONS)
    assert second["changed"] is False
    assert world.state_shape_canonical() == shape


def test_idem_002_a_mutated_batch_changes_the_shape():
    world = WorldModel("conf", clock=clock)
    world.ingest(OBSERVATIONS)
    shape = world.state_shape_canonical()
    mutated = [{**OBSERVATIONS[0], "title": OBSERVATIONS[0]["title"] + " (edited)"}, OBSERVATIONS[1]]
    assert world.ingest(mutated)["changed"] is True
    assert world.state_shape_canonical() != shape


def test_bitemp_001_superseding_edge_closes_the_old_one():
    world = WorldModel("conf")

    def at(s):
        return {"kind": "manual", "at": s}

    world.upsert_entity(type="player", external_key={"system": "g", "id": "p1"}, attrs={}, source=at("2087-01-01T00:00:00.000Z"))
    world.upsert_entity(type="team", external_key={"system": "g", "id": "a"}, attrs={}, source=at("2087-01-01T00:00:00.000Z"))
    world.upsert_entity(type="team", external_key={"system": "g", "id": "b"}, attrs={}, source=at("2088-03-01T00:00:00.000Z"))
    world.relate("player:g:p1", "plays-for", "team:g:a", valid_from="2087-01-01T00:00:00.000Z", source=at("2087-01-01T00:00:00.000Z"))
    world.relate("player:g:p1", "plays-for", "team:g:b", valid_from="2088-03-01T00:00:00.000Z", source=at("2088-03-01T00:00:00.000Z"))
    graph = world.view("graph")
    assert [e["id"] for e in graph.neighbors_of("player:g:p1", via="plays-for")] == ["team:g:b"]
    assert [e["id"] for e in graph.neighbors_of("player:g:p1", via="plays-for", at="2087-06-01T00:00:00.000Z")] == ["team:g:a"]


def test_audit_001_every_mutation_writes_an_audit_entry_in_order():
    world = WorldModel("conf")
    world.upsert_entity(type="x", name="Audit One", source={"kind": "manual", "at": "2026-01-01T00:00:00.000Z"})
    world.upsert_entity(type="x", name="Audit Two", source={"kind": "manual", "at": "2026-01-02T00:00:00.000Z"})
    audit = world.audit()
    assert len(audit) >= 2
    assert all(b["seq"] > a["seq"] for a, b in zip(audit, audit[1:]))


# ----- parity with the TypeScript reference -----

REFERENCE_ENTITY_IDS = {
    "José  García": "ent_a630f9d8c09ef23a",
    "Jose Garcia": "ent_a630f9d8c09ef23a",
    "Acme Corp": "ent_5bc61993666a4e6b",
    "Acme Corporation": "ent_ad89eb3f23fb6b92",
    "Zoë​Saldaña": "ent_da869916b06dcf50",
    "  Ann O'Neil ": "ent_9b37961aaac2ebde",
    "Ｆｕｌｌｗｉｄｔｈ": "ent_a55eab9b71a234c9",
    "Graph Neural Networks for Drug Discovery": "ent_4dc85603f42d4f06",
}


@pytest.mark.parametrize("name, expected", REFERENCE_ENTITY_IDS.items())
def test_entity_ids_match_the_reference(name, expected):
    assert entity_id_from_name("author", name) == expected


def test_other_ids_match_the_reference():
    assert context_id_from_attrs("run", {"b": 2, "a": "x", "nested": {"z": [1, "two"], "y": None}}, "parent:1") == "ctx_e4d54a78a76d20f6"
    assert relationship_id("paper:openalex:W1", "member-of", "cluster:litagent:r1:C1", "run:litagent:r1",
                           "2026-10-24T00:00:00.000Z") == "rel_1e19f15a61f2ea5c"
    assert fact_id("cluster:litagent:r1:C1", "grade", {"total": 8, "fix": None}, "2026-10-24T00:00:00.000Z", "agent") == "fact_80b21518618f6670"
    assert canonical_json({"b": [3, {"d": 1, "c": "é"}], "a": 'q"uote'}) == '{"a":"q\\"uote","b":[3,{"c":"é","d":1}]}'
    assert external_id("paper", "openalex", "W123") == "paper:openalex:W123"


@pytest.mark.parametrize("a, b, similarity, decision", [
    ("J. Smith", "J Smith", 0.875, "auto-merge"),
    ("Yang Liu", "Yang Lu", 0.875, "auto-merge"),
    ("Wei Wang", "Wei Zhang", 0.7777777777777778, "new"),
    ("Jonathan Smith", "Jonathon Smith", 0.9285714285714286, "auto-merge"),
    ("Kim", "Kimberly", 0.375, "new"),
])
def test_name_similarity_matches_the_reference(a, b, similarity, decision):
    assert name_similarity(a, b) == pytest.approx(similarity, abs=1e-12)
    assert decide(name_similarity(a, b)) == decision


# ----- behaviour beyond the suite that litagent relies on -----

SRC = {"kind": "agent", "at": "2026-10-24T00:00:00.000Z"}


def test_near_duplicate_names_auto_merge_into_one_entity():
    world = WorldModel("t")
    first = world.upsert_entity(type="author", name="Jonathan Smith", source=SRC)
    second = world.upsert_entity(type="author", name="Jonathon Smith", source=SRC)
    assert second["id"] == first["id"]
    assert "Jonathon Smith" in second["aliases"]
    assert any(a["kind"] == "auto-merge" for a in world.audit())


def test_review_band_names_queue_for_the_operator():
    world = WorldModel("t")
    a = world.upsert_entity(type="author", name="Maria Chen", source=SRC)
    b = world.upsert_entity(type="author", name="Mario Chen", source=SRC)  # 0.9 -> auto
    c = world.upsert_entity(type="author", name="Marta Chan", source=SRC)  # 0.8 -> new
    assert b["id"] == a["id"] and c["id"] != a["id"]

    queued = WorldModel("t")
    queued.upsert_entity(type="author", name="abcdefghijklmnopqrstuvwxyz0123456789ab", source=SRC)
    queued.upsert_entity(type="author", name="abcdefghijklmnopqrstuvwxyz012345XXXXXXX", source=SRC)  # 0.82
    proposals = queued.merge_queue()
    assert len(proposals) == 1 and proposals[0]["status"] == "pending"
    queued.approve_merge(proposals[0]["id"], by="operator")
    assert proposals[0]["status"] == "approved"


def test_most_recent_fact_wins_and_older_is_kept():
    world = WorldModel("t")
    world.upsert_entity(type="cluster", external_key={"system": "litagent", "id": "C1"}, source=SRC)
    world.assert_fact("cluster:litagent:C1", "grade", 5, source={"kind": "agent", "at": "2026-10-24T00:00:00.000Z"})
    world.assert_fact("cluster:litagent:C1", "grade", 8, source={"kind": "agent", "at": "2026-10-24T00:01:00.000Z"})
    assert world.view("graph").entity("cluster:litagent:C1")["attrs"]["grade"] == 8
    facts = world.view("facts").about("cluster:litagent:C1")
    assert [f["value"] for f in facts] == [5, 8] and facts[0]["supersededBy"] == facts[1]["id"]


def test_snapshot_view_replays_up_to_a_time():
    world = WorldModel("t")
    world.upsert_entity(type="paper", external_key={"system": "o", "id": "W1"}, attrs={"v": 1}, source={"kind": "a", "at": "2026-01-01T00:00:00.000Z"})
    world.upsert_entity(type="paper", external_key={"system": "o", "id": "W1"}, attrs={"v": 2}, source={"kind": "a", "at": "2026-02-01T00:00:00.000Z"})
    assert world.view("snapshot").entity_at("paper:o:W1", "2026-01-15")["attrs"]["v"] == 1
    assert world.view("graph").entity("paper:o:W1")["attrs"]["v"] == 2


def test_local_storage_round_trips_through_the_event_log(tmp_path):
    world = WorldModel("run-1", storage="local", directory=str(tmp_path))
    world.upsert_entity(type="paper", external_key={"system": "o", "id": "W1"}, attrs={"title": "T"}, source=SRC)
    world.upsert_entity(type="paper", external_key={"system": "o", "id": "W2"}, attrs={}, source=SRC)
    world.relate("paper:o:W1", "cites", "paper:o:W2", source=SRC)
    world.flush()
    assert (tmp_path / "world-run-1.json").exists()
    reloaded = WorldModel("run-1", storage="local", directory=str(tmp_path))
    assert reloaded.state_shape_canonical() == world.state_shape_canonical()
    assert len(reloaded.audit()) == len(world.audit())


def test_fast_similarity_agrees_with_the_reference_levenshtein():
    import random

    from litagent.integrations.world_model.resolve import levenshtein, normalized_similarity

    rng = random.Random(7)
    words = ["".join(rng.choice("abcde fgh") for _ in range(rng.randint(0, 25))) for _ in range(500)]
    for a, b in zip(words, words[1:]):
        expected = 1 - levenshtein(a, b) / max(len(a), len(b)) if max(len(a), len(b)) else 1.0
        assert normalized_similarity(a, b) == pytest.approx(expected, abs=1e-12)
