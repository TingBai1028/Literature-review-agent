"""2. Retriever agent. Spec: docs/agents/retriever.md

Runs the Planner's queries against scholarly APIs, removes duplicates, caps the number
of papers by effort level, and builds the summary shown at Human review 1.
"""

from __future__ import annotations

from litagent.config import EFFORT_PROFILES, Settings
from litagent.schemas import Paper, RetrievalSummary, SearchPlan
from litagent.tools.openalex import search_openalex


def retrieve(plan: SearchPlan, settings: Settings, signed_in: bool = False) -> list[Paper]:
    if settings.dry_run:
        return _fake_papers(plan.max_papers)

    papers: list[Paper] = []
    for query in plan.queries:
        papers += search_openalex(query, plan.criteria, limit=plan.max_papers, open_access_only=not signed_in)
        # TODO: add search_semantic_scholar / search_arxiv and merge the results

    if signed_in:
        # TODO: institutional access. Check your university's licence terms first:
        # publisher licences usually forbid automated bulk downloading.
        pass

    papers = deduplicate(papers)
    # TODO: rank by relevance to the question and citations per year before cutting
    papers = papers[: plan.max_papers]

    if EFFORT_PROFILES[plan.effort].use_full_text:
        # TODO: download PDFs for open-access papers and fill paper.full_text
        pass
    return papers


def deduplicate(papers: list[Paper]) -> list[Paper]:
    """Same paper from two sources, or preprint + published version: keep the first."""
    seen: set[str] = set()
    unique = []
    for p in papers:
        key = (p.doi or p.title).lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def summarise(papers: list[Paper], plan: SearchPlan, settings: Settings) -> RetrievalSummary:
    if settings.dry_run:
        text = f"Found {len(papers)} papers on '{plan.criteria.topic}' from {plan.criteria.year_from} onward."
        return RetrievalSummary(papers=papers, summary=text)
    # TODO: short LLM summary of what was found (main themes, year range, review vs primary split)
    raise NotImplementedError


def _fake_papers(n: int) -> list[Paper]:
    return [
        Paper(
            id=f"P{i}",
            title=f"Fake paper {i}",
            abstract=f"Abstract of fake paper {i}.",
            year=2022 + i % 4,
            citation_count=10 * i,
            is_open_access=True,
            source="fake",
        )
        for i in range(1, n + 1)
    ]
