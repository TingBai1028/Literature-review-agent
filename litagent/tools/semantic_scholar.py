"""Semantic Scholar tool. Docs: https://api.semanticscholar.org/api-docs/

Useful for citation links (references / citations of a paper), which help the
Connection finder.

name: search_semantic_scholar / get_citations
inputs: query or paper id
output: list[Paper]
fail mode: TODO (rate limits are strict without an API key)
"""

from __future__ import annotations

from litagent.schemas import Paper, SearchCriteria


def search_semantic_scholar(query: str, criteria: SearchCriteria, limit: int = 25) -> list[Paper]:
    # TODO: GET https://api.semanticscholar.org/graph/v1/paper/search
    raise NotImplementedError


def get_citations(paper_id: str) -> list[str]:
    # TODO: GET https://api.semanticscholar.org/graph/v1/paper/{paper_id}/references
    raise NotImplementedError
