"""5. Gap finder agent. Spec: docs/agents/gap_finder.md

Looks for research gaps inside a cluster, only between papers whose similarity is in a
set range (related enough to be comparable, different enough to leave room for a gap).
"""

from __future__ import annotations

from litagent.config import Settings
from litagent.schemas import Cluster, Connection, Evidence, Gap, Paper

# TODO: tune. Too high -> papers are near duplicates; too low -> unrelated, so the "gap" is meaningless.
SIMILARITY_RANGE = (0.5, 0.8)


def find_gaps(
    papers: list[Paper],
    clusters: list[Cluster],
    connections: list[Connection],
    settings: Settings,
    fix: str | None = None,
) -> list[Gap]:
    if settings.dry_run:
        return _fake_gaps(clusters)

    # TODO: for each cluster, pick paper pairs inside SIMILARITY_RANGE.
    # TODO: ask the LLM (prompts/gap_finder.md) what is missing between them, with quotes.
    # TODO: before reporting a gap, run a quick targeted search to check it isn't already covered.
    raise NotImplementedError


def _fake_gaps(clusters: list[Cluster]) -> list[Gap]:
    return [
        Gap(
            id=f"{c.id}-G1",
            cluster_id=c.id,
            description="Dry run: no study combines method X with setting Y.",
            between_paper_ids=c.paper_ids[:2],
            why_it_matters="Dry run",
            evidence=[Evidence(paper_id=c.paper_ids[0], quote="fake quote")],
        )
        for c in clusters
        if c.paper_ids
    ]
