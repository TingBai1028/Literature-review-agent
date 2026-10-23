"""arXiv tool: preprints with free full-text PDFs. Docs: https://info.arxiv.org/help/api/

name: search_arxiv
inputs: query, SearchCriteria, limit
output: list[Paper] (pdf_url always set)
fail mode: TODO (arXiv asks for at most one request every 3 seconds)
"""

from __future__ import annotations

from litagent.schemas import Paper, SearchCriteria


def search_arxiv(query: str, criteria: SearchCriteria, limit: int = 25) -> list[Paper]:
    # TODO: GET http://export.arxiv.org/api/query?search_query=...  (returns Atom XML)
    raise NotImplementedError
