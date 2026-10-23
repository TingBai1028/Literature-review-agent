"""4. Connection finder agent. Spec: docs/agents/connection_finder.md

Finds connections within each cluster first, then between clusters.
Every connection must carry Evidence (paper id + verbatim quote).
"""

from __future__ import annotations

from litagent.config import Settings
from litagent.schemas import Cluster, Connection, Evidence, Paper


def find_connections(papers: list[Paper], clusters: list[Cluster], settings: Settings, fix: str | None = None) -> list[Connection]:
    if settings.dry_run:
        return _fake_connections(clusters)

    # TODO: within each cluster: decide which paper pairs to compare (all pairs? top-k most similar?),
    #       then ask the LLM (prompts/connection_finder.md) how they connect, with quotes.
    # TODO: between clusters: compare cluster summaries or representative papers.
    # TODO: optional: use citation links from Semantic Scholar as extra evidence.
    raise NotImplementedError


def _fake_connections(clusters: list[Cluster]) -> list[Connection]:
    out = []
    for c in clusters:
        if len(c.paper_ids) >= 2:
            a, b = c.paper_ids[:2]
            out.append(
                Connection(
                    id=f"{c.id}-K1",
                    kind="within_cluster",
                    paper_ids=[a, b],
                    cluster_ids=[c.id],
                    description="Dry run: both papers study the same problem.",
                    evidence=[Evidence(paper_id=a, quote="fake quote"), Evidence(paper_id=b, quote="fake quote")],
                )
            )
    return out
