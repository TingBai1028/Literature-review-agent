"""Meterless World Model: the shared findings graph that /run returns as the paper map.

Today WorldModel is our in-memory stand-in (see litagent/integrations/meterless.py).
These tests describe the behaviour the real engine must keep once it is wired in.
"""

from litagent.config import Effort, Settings
from litagent.human_review import AutoApproveReviewer
from litagent.integrations.meterless import WorldModel
from litagent.orchestrator import run_pipeline
from litagent.schemas import Cluster, Connection, Evidence, Gap, Paper


def build_world() -> WorldModel:
    world = WorldModel()
    world.add_papers([Paper(id=f"P{i}", title=f"Paper {i}", year=2023, source="test") for i in range(1, 5)])
    world.write_clusters([
        Cluster(id="C1", label="A", paper_ids=["P1", "P2"], rationale="r"),
        Cluster(id="C2", label="B", paper_ids=["P3", "P4"], rationale="r"),
    ])
    world.write_connections([
        Connection(id="K1", kind="between_clusters", paper_ids=["P1", "P3"], cluster_ids=["C1", "C2"],
                   description="d", evidence=[Evidence(paper_id="P1", quote="q")]),
    ])
    world.write_gaps([Gap(id="G1", cluster_id="C1", description="d", between_paper_ids=["P1", "P2"],
                          why_it_matters="w", evidence=[Evidence(paper_id="P1", quote="q")])])
    return world


def test_later_agents_read_what_earlier_agents_wrote():
    world = build_world()
    assert world.read_clusters() == {"C1": ["P1", "P2"], "C2": ["P3", "P4"]}
    [conn] = world.read_connections()
    assert (conn["source"], conn["target"], conn["type"]) == ("P1", "P3", "between_clusters")
    assert conn["evidence"] == [{"paper_id": "P1", "quote": "q"}]


def test_graph_json_has_every_node_type_and_edge():
    graph = build_world().to_graph_json()
    types = {n["type"] for n in graph["nodes"]}
    assert types == {"paper", "cluster", "gap"}
    edge_types = {e["type"] for e in graph["edges"]}
    assert edge_types == {"belongs_to", "between_clusters", "gap_near"}
    node_ids = {n["id"] for n in graph["nodes"]}
    assert all(e["source"] in node_ids and e["target"] in node_ids for e in graph["edges"])


def test_run_returns_paper_map_from_world_model(tmp_path):
    settings = Settings()
    settings.sample_mode = True
    settings.logs_dir = str(tmp_path)
    result = run_pipeline("graph neural networks for drug discovery", Effort.NORMAL, AutoApproveReviewer(), settings)

    nodes = {n["id"]: n for n in result.paper_map["nodes"]}
    assert all(c.id in nodes and nodes[c.id]["type"] == "cluster" for c in result.clusters)
    assert all(g.id in nodes and nodes[g.id]["type"] == "gap" for g in result.gaps)
    assert sum(1 for n in nodes.values() if n["type"] == "paper") == len(result.papers)
    belongs = [e for e in result.paper_map["edges"] if e["type"] == "belongs_to"]
    assert len(belongs) == sum(len(c.paper_ids) for c in result.clusters)
