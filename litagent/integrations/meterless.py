"""Meterless: world model (shared findings graph) and Markovian engine (chunked reading).

WorldModel: each agent writes its findings here as nodes and edges; the next agent reads
from it, and the front end renders it as the paper map. The in-memory version below works
for dry runs and defines the interface the real Meterless world model should fill.

TODO:
- Download the world model and Markovian engine primitives from the Resources tab in the
  Agentathon app and replace the in-memory parts below.
- Ask in the Help Meterless channel which integration counts for Sponsor Tech points.
"""

from __future__ import annotations

from typing import Any

from litagent.schemas import Cluster, Connection, Gap, Paper


class WorldModel:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: list[dict[str, Any]] = []

    # ----- writes (one per agent) -----

    def add_papers(self, papers: list[Paper]) -> None:
        for p in papers:
            self.nodes[p.id] = {"type": "paper", "title": p.title, "year": p.year}

    def write_clusters(self, clusters: list[Cluster]) -> None:
        for c in clusters:
            self.nodes[c.id] = {"type": "cluster", "label": c.label, "rationale": c.rationale}
            for pid in c.paper_ids:
                self.edges.append({"source": pid, "target": c.id, "type": "belongs_to"})

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

    def write_gaps(self, gaps: list[Gap]) -> None:
        for g in gaps:
            self.nodes[g.id] = {"type": "gap", "description": g.description, "why_it_matters": g.why_it_matters}
            for pid in g.between_paper_ids:
                self.edges.append({"source": g.id, "target": pid, "type": "gap_near"})

    # ----- reads -----

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
