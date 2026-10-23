"""4. Connection finder agent. Spec: docs/agents/connection_finder.md

Finds connections within each cluster first, then between clusters.
Every connection must carry Evidence (paper id + verbatim quote).
"""

from __future__ import annotations

from litagent.config import Settings
from litagent.schemas import Cluster, Connection, Evidence, Paper


def find_connections(papers: list[Paper], clusters: list[Cluster], settings: Settings, fix: str | None = None) -> list[Connection]:
    if settings.sample_mode:
        return _fake_connections(papers, clusters)

    # TODO: within each cluster: decide which paper pairs to compare (all pairs? top-k most similar?),
    #       then ask the LLM (prompts/connection_finder.md) how they connect, with quotes.
    # TODO: between clusters: compare cluster summaries or representative papers.
    # TODO: optional: use citation links from Semantic Scholar as extra evidence.
    raise NotImplementedError


def _fake_connections(papers: list[Paper], clusters: list[Cluster]) -> list[Connection]:
    """Sample mode: link the first two papers of each cluster, quoting their abstracts verbatim."""
    by_id = {p.id: p for p in papers}
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
                    description="Sample mode: placeholder connection between two papers in the same group.",
                    evidence=[Evidence(paper_id=a, quote=first_sentence(by_id.get(a))),
                              Evidence(paper_id=b, quote=first_sentence(by_id.get(b)))],
                )
            )
    return out


def first_sentence(paper: Paper | None, limit: int = 200) -> str:
    """A verbatim snippet from the abstract (or title), used as sample-mode evidence."""
    if paper is None:
        return ""
    text = paper.abstract or paper.title
    end = text.find(". ")
    return text[: end + 1 if 0 < end < limit else limit]
