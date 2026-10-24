"""litagent on the Meterless World Model: the shared findings graph that /run returns as the paper map.

The engine itself is checked against the Meterless spec in tests/test_world_model_conformance.py;
these tests check how litagent's agents write to it and read from it.
"""

import json

import pytest

from litagent.config import Effort, Settings
from litagent.human_review import AutoApproveReviewer, HumanFeedback
from litagent.integrations.meterless import ResearchWorld, load_world
from litagent.orchestrator import run_pipeline
from litagent.schemas import Cluster, Connection, Evidence, Gap, Grade, Paper


def paper(pid, authors=()):
    return Paper(id=pid, title=f"Paper {pid}", year=2023, authors=list(authors), source="test")


def build_world(directory=None) -> ResearchWorld:
    world = ResearchWorld(run_id="t-1", directory=directory)
    world.start_attempt(1, "How do GNNs predict drug-target interactions?", ["gnn drug target"])
    world.add_papers([
        paper("P1", ["José García", "Ana Lima"]),
        paper("P2", ["Jose  Garcia", "Jonathan Smith"]),  # same author as P1's, different spelling
        paper("P5", ["Jonathon Smith"]),  # a near-match, not necessarily the same person
        paper("P3", ["Wei Zhang"]),
        paper("P4"),
    ])
    world.write_clusters([
        Cluster(id="C1", label="A", paper_ids=["P1", "P2"], rationale="r"),
        Cluster(id="C2", label="B", paper_ids=["P3", "P4"], rationale="r"),
    ])
    world.write_connections([
        Connection(id="K1", kind="within_cluster", paper_ids=["P1", "P2"], cluster_ids=["C1"],
                   description="d", evidence=[Evidence(paper_id="P1", quote="q")]),
        Connection(id="K2", kind="between_clusters", paper_ids=["P1", "P3"], cluster_ids=["C1", "C2"],
                   description="d2", evidence=[Evidence(paper_id="P3", quote="q3")]),
    ])
    world.write_gaps([Gap(id="G1", cluster_id="C1", description="gap", between_paper_ids=["P1", "P2"],
                          why_it_matters="w", evidence=[Evidence(paper_id="P1", quote="q")])])
    return world


def test_later_agents_read_what_earlier_agents_wrote():
    world = build_world()
    assert world.read_clusters() == {"C1": ["P1", "P2"], "C2": ["P3", "P4"]}
    conns = {(c["source"], c["target"]): c for c in world.read_connections()}
    assert set(conns) == {("P1", "P2"), ("P1", "P3")}  # both kept: connects-to is multi-valued
    assert conns[("P1", "P3")]["kind"] == "between_clusters"
    assert conns[("P1", "P3")]["evidence"] == [{"paper_id": "P3", "quote": "q3"}]
    assert conns[("P1", "P3")]["by"] == "connection_finder"


def test_cluster_context_gives_the_next_agent_papers_and_connections():
    ctx = build_world().cluster_context("C1")
    assert ctx["cluster"] == {"label": "A", "rationale": "r"}
    assert [p["id"] for p in ctx["papers"]] == ["P1", "P2"]
    assert [(c["source"], c["target"]) for c in ctx["connections"]] == [("P1", "P2")]  # P1-P3 crosses clusters


def test_same_normalized_author_is_shared_but_near_matches_only_queue():
    world = build_world()
    assert len(world.shared_authors("P1", "P2")) == 1  # José García / Jose  Garcia: one author
    assert world.shared_authors("P2", "P5") == []  # Jonathan vs Jonathon Smith: not merged automatically
    proposals = world.world.merge_queue()
    assert [(p["leftName"], p["rightName"]) for p in proposals] == [("Jonathon Smith", "Jonathan Smith")]
    assert not any(a["kind"] == "auto-merge" for a in world.world.audit())
    assert world.to_graph_json()["world"]["pending_merges"] == 1


def test_short_names_that_differ_by_a_letter_stay_separate_people():
    world = ResearchWorld(run_id="t-2")
    world.add_papers([paper("A", ["Liang Li"]), paper("B", ["Xiang Li"]), paper("C", ["Yu Wang"]), paper("D", ["Yu Kang"])])
    assert world.shared_authors("A", "B") == [] and world.shared_authors("C", "D") == []


def test_graph_json_has_every_node_type_and_edge():
    graph = build_world().to_graph_json()
    assert {n["type"] for n in graph["nodes"]} == {"paper", "cluster", "gap"}
    assert {e["type"] for e in graph["edges"]} == {"member-of", "connects-to", "between"}
    ids = {n["id"] for n in graph["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in graph["edges"])
    paper_node = next(n for n in graph["nodes"] if n["id"] == "P1")
    assert paper_node["world_id"] == "paper:test:P1"
    assert graph["world"]["run_id"] == "t-1" and graph["world"]["events"] > 0


def test_every_write_carries_provenance():
    world = build_world()
    rels = world.world.view("graph").relationships()
    assert rels and all(r["source"]["runId"] == "t-1" and r["source"]["by"] for r in rels)
    by = {r["type"]: r["source"]["by"] for r in rels}
    assert by["member-of"] == "clusterer" and by["between"] == "gap_finder" and by["authored-by"] == "retriever"


def test_a_replan_starts_a_clean_map_but_keeps_history():
    world = build_world()
    events = len(world.world.events())
    world.start_attempt(2, "Same question, reviews only", ["gnn review"])
    world.add_papers([paper("P9")])
    graph = world.to_graph_json()
    assert [n["id"] for n in graph["nodes"]] == ["P9"]
    assert graph["world"]["attempt"] == 2
    assert len(world.world.events()) > events  # attempt 1 is still in the event log


def test_grades_are_facts_and_the_latest_wins():
    world = build_world()
    world.record_grade("clusters", Grade(stage="clusters", accuracy=1, appropriateness=1, actionability=1, fix="split C1"))
    world.record_grade("clusters", Grade(stage="clusters", accuracy=3, appropriateness=3, actionability=2))
    stage_id = "stage:litagent:t-1:1:clusters"
    assert world.world.view("graph").entity(stage_id)["attrs"]["grade"]["accuracy"] == 3
    facts = world.world.view("facts").about(stage_id)
    assert len(facts) == 2 and facts[0]["supersededBy"] == facts[1]["id"]


def test_world_is_saved_and_reloads(tmp_path):
    world = build_world(str(tmp_path))
    saved = json.loads((tmp_path / "world-t-1.json").read_text())
    assert len(saved["events"]) == len(world.world.events())
    reloaded = load_world("t-1", str(tmp_path))
    assert reloaded.state_shape_canonical() == world.world.state_shape_canonical()
    assert load_world("missing", str(tmp_path)) is None


@pytest.fixture
def settings(tmp_path):
    s = Settings()
    s.sample_mode = True
    s.logs_dir = str(tmp_path)
    return s


def test_run_returns_paper_map_from_world_model(settings, tmp_path):
    result = run_pipeline("graph neural networks for drug discovery", Effort.NORMAL, AutoApproveReviewer(), settings)
    nodes = {n["id"]: n for n in result.paper_map["nodes"]}
    assert all(nodes[c.id]["type"] == "cluster" for c in result.clusters)
    assert all(nodes[g.id]["type"] == "gap" for g in result.gaps)
    assert sum(1 for n in nodes.values() if n["type"] == "paper") == len(result.papers)
    member_of = [e for e in result.paper_map["edges"] if e["type"] == "member-of"]
    assert len(member_of) == sum(len(c.paper_ids) for c in result.clusters)
    assert (tmp_path / f"world-{result.run_id}.json").exists()
    world = load_world(result.run_id, str(tmp_path))
    stages = {e["attrs"]["stage"] for e in world.view("graph").query(type="stage")}
    assert stages == {"clusters", "connections", "gaps"}  # every grade recorded as a fact


class RejectFirstReviewer(AutoApproveReviewer):
    def __init__(self):
        self.calls = 0

    def review_papers(self, summary):
        self.calls += 1
        return HumanFeedback(approved=self.calls > 1, comment=None if self.calls > 1 else "only reviews")


def test_replanned_run_maps_only_the_final_attempt(settings):
    result = run_pipeline("graph neural networks for drug discovery", Effort.NORMAL, RejectFirstReviewer(), settings)
    assert result.paper_map["world"]["attempt"] == 2
    assert sum(1 for n in result.paper_map["nodes"] if n["type"] == "paper") == len(result.papers)


def test_rerunning_a_run_id_starts_a_fresh_world(settings):
    first = run_pipeline("graph neural networks for drug discovery", Effort.NORMAL, AutoApproveReviewer(), settings)
    second = run_pipeline("graph neural networks for drug discovery", Effort.NORMAL, AutoApproveReviewer(), settings,
                          run_id=first.run_id)
    assert second.paper_map == first.paper_map
