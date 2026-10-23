"""Zetaris: shared paper data layer.

The Retriever writes papers here; every later agent reads papers through this class
instead of calling the scholarly APIs again. In dry-run mode it is an in-memory dict,
so the pipeline works before Zetaris is connected.

TODO:
- Watch the Data Day recording on HackOS and confirm how to connect (driver, REST, SQL endpoint).
- Decide the table layout, e.g. papers(id, title, abstract, year, authors, citation_count, ...).
- Optional stretch goal: join the user's own library (uploaded PDFs / reference export) as a second source.
"""

from __future__ import annotations

import os

from litagent.schemas import Paper


class ZetarisStore:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self._papers: dict[str, Paper] = {}
        if not dry_run:
            self.url = os.getenv("ZETARIS_URL")
            # TODO: open a connection here

    def save_papers(self, papers: list[Paper]) -> None:
        if self.dry_run:
            self._papers.update({p.id: p for p in papers})
            return
        raise NotImplementedError("TODO: insert papers into Zetaris")

    def get_papers(self, paper_ids: list[str] | None = None) -> list[Paper]:
        if self.dry_run:
            if paper_ids is None:
                return list(self._papers.values())
            return [self._papers[i] for i in paper_ids if i in self._papers]
        raise NotImplementedError("TODO: query papers from Zetaris")

    def query(self, sql: str) -> list[dict]:
        """Free-form SQL for agents that need it, e.g. filter by year or citation count."""
        raise NotImplementedError("TODO: run SQL through Zetaris")
