"""OpenAlex search tool: free, no key needed. Docs: https://docs.openalex.org

name: search_openalex
inputs: query, SearchCriteria, limit
output: list[Paper]
fail mode: HTTP error or rate limit -> retry with backoff, then return [] and let the Retriever
           fall back to another source.

This is a working starting point. Check it against the docs before relying on it.
"""

from __future__ import annotations

import os
import time

import httpx

from litagent.schemas import Paper, SearchCriteria

BASE_URL = "https://api.openalex.org/works"


def search_openalex(query: str, criteria: SearchCriteria, limit: int = 25, open_access_only: bool = True) -> list[Paper]:
    filters = []
    if criteria.year_from:
        filters.append(f"from_publication_date:{criteria.year_from}-01-01")
    if criteria.year_to:
        filters.append(f"to_publication_date:{criteria.year_to}-12-31")
    if open_access_only:
        filters.append("is_oa:true")
    if criteria.paper_types == ["review"]:
        filters.append("type:review")

    params = {"search": query, "per-page": min(limit, 200)}
    if filters:
        params["filter"] = ",".join(filters)
    if email := os.getenv("OPENALEX_EMAIL"):
        params["mailto"] = email

    data = _get_with_retry(BASE_URL, params)
    if data is None:
        return []
    return [_to_paper(w) for w in data.get("results", [])]


def _get_with_retry(url: str, params: dict, attempts: int = 3) -> dict | None:
    for i in range(attempts):
        try:
            r = httpx.get(url, params=params, timeout=30)
            if r.status_code == 429:
                time.sleep(2**i)
                continue
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError:
            time.sleep(2**i)
    return None


def _to_paper(work: dict) -> Paper:
    oa = work.get("open_access") or {}
    return Paper(
        id=work["id"].rsplit("/", 1)[-1],
        title=work.get("display_name") or "",
        abstract=_rebuild_abstract(work.get("abstract_inverted_index")),
        year=work.get("publication_year"),
        authors=[a["author"]["display_name"] for a in work.get("authorships", []) if a.get("author")],
        citation_count=work.get("cited_by_count"),
        is_review=work.get("type") == "review",
        is_open_access=bool(oa.get("is_oa")),
        pdf_url=oa.get("oa_url"),
        doi=work.get("doi"),
        source="openalex",
    )


def _rebuild_abstract(inverted_index: dict | None) -> str | None:
    """OpenAlex stores abstracts as {word: [positions]}; turn it back into text."""
    if not inverted_index:
        return None
    positions = [(pos, word) for word, poss in inverted_index.items() for pos in poss]
    return " ".join(word for _, word in sorted(positions))
