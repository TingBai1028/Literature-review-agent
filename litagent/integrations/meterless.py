"""Meterless: world model (shared findings graph) and Markovian engine (chunked reading).

WorldModel: each agent writes its findings here as nodes and edges; the next agent reads
from it, and /run returns it as `paper_map`, which the front end renders as the paper map.

Status: the class below is our own in-memory stand-in, NOT the Meterless engine yet. It defines
the interface, and tests/test_meterless_world_model.py checks the behaviour, so the same test
covers the real engine once it is wired in.

TODO (wire the real Meterless World Model):
- Download the world model primitive from the Resources tab in the Agentathon app.
- Keep the public methods (add_papers, write_*, read_*, to_graph_json) and back them with the
  engine; keep the in-memory version for sample mode, like ZetarisStore does.
- Ask in the Help Meterless channel which integration counts for Sponsor Tech points.
"""

from __future__ import annotations

from typing import Any

from litagent.schemas import Cluster, Connection, Gap, Paper
from litagent.trace import current_trace


class WorldModel:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: list[dict[str, Any]] = []

    # ----- writes (one per agent) -----

    def add_papers(self, papers: list[Paper]) -> None:
        for p in papers:
            self.nodes[p.id] = {"type": "paper", "title": p.title, "year": p.year}
        _log("write papers", len(papers))

    def write_clusters(self, clusters: list[Cluster]) -> None:
        for c in clusters:
            self.nodes[c.id] = {"type": "cluster", "label": c.label, "rationale": c.rationale}
            for pid in c.paper_ids:
                self.edges.append({"source": pid, "target": c.id, "type": "belongs_to"})
        _log("write clusters", len(clusters))

    def write_connections(self, connections: list[Connection]) -> None:
        for conn in connections:
            if len(conn.paper_ids) >= 2:
                self.edges.append(
                    {
                        "source": conn.paper_ids[0],
                        "target": conn.paper_ids[1],
                        "type": conn.kind,
                        "description": conn.description,
                        "evidence": [e.model_dump() for e in conn.evidence],
                    }
                )
        _log("write connections", len(connections))

    def write_gaps(self, gaps: list[Gap]) -> None:
        for g in gaps:
            self.nodes[g.id] = {"type": "gap", "description": g.description, "why_it_matters": g.why_it_matters}
            for pid in g.between_paper_ids:
                self.edges.append({"source": g.id, "target": pid, "type": "gap_near"})
        _log("write gaps", len(gaps))

    # ----- reads -----

    def read_clusters(self) -> dict[str, list[str]]:
        """Cluster id -> paper ids, as the next agent sees them."""
        out: dict[str, list[str]] = {k: [] for k, v in self.nodes.items() if v["type"] == "cluster"}
        for e in self.edges:
            if e["type"] == "belongs_to":
                out.setdefault(e["target"], []).append(e["source"])
        return out

    def read_connections(self) -> list[dict[str, Any]]:
        return [e for e in self.edges if e["type"] in ("within_cluster", "between_clusters")]

    def to_graph_json(self) -> dict[str, Any]:
        """What the front end renders as the paper map."""
        return {
            "nodes": [{"id": k, **v} for k, v in self.nodes.items()],
            "edges": self.edges,
        }


def read_in_chunks(text: str, task: str) -> str:
    """Markovian engine: read a long full-text paper in chunks, carrying compressed state forward.

    Used at High / Ultra effort. TODO: replace with the Meterless Markovian engine.
    """
    raise NotImplementedError("TODO: connect the Meterless Markovian engine")


def _log(action: str, count: int) -> None:
    if trace := current_trace():
        trace.log("meterless_world_model", action, f"{count} written", why="Shared findings graph for the next agent and the paper map")
