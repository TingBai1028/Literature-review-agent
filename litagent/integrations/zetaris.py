"""Zetaris: shared paper data layer.

The Retriever writes papers here; every later agent reads papers through this class
instead of calling the scholarly APIs again. In sample mode it is an in-memory dict,
so the pipeline works without Zetaris running.

Zetaris runs locally in Docker. Connection settings (names from
https://github.com/zetaris/getting-started/blob/main/.env.example):
ZETARIS_REST_URL (default http://localhost:8888/api/v1.0), ZETARIS_ORG_ID, ZETARIS_API_KEY.
From inside our container, use host.docker.internal instead of localhost.

TODO:
- Decide the datasource and table layout, e.g. papers(id, title, abstract, year, authors, citation_count, ...).
  See docs/connections/ and docs/guides/first-dataset.md in the getting-started repo.
- Implement save_papers / get_papers on top of ZetarisRestClient.run_sql once the table exists.
- Optional stretch goal: join the user's own library (uploaded PDFs / reference export) as a second source.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import httpx

from litagent.schemas import Paper
from litagent.trace import current_trace

DEFAULT_REST_URL = "http://localhost:8888/api/v1.0"


class ZetarisError(RuntimeError):
    pass


class ZetarisRestClient:
    """Documented Zetaris REST API (same call as scripts/zetaris_sql.py RestChannel in the getting-started repo)."""

    def __init__(self, timeout_s: float = 45.0):
        self.base = os.getenv("ZETARIS_REST_URL", DEFAULT_REST_URL).rstrip("/")
        self.org_id = os.getenv("ZETARIS_ORG_ID", "1")
        self._api_key = os.getenv("ZETARIS_API_KEY")
        if not self._api_key:
            raise ZetarisError("Set ZETARIS_API_KEY (create it in the Zetaris GUI), or run with SAMPLE_MODE=true.")
        self.timeout_s = timeout_s

    def run_sql(self, sql: str, limit: int = 1000) -> list[list[Any]]:
        try:
            r = httpx.post(
                f"{self.base}/sql-editor/sqls/run",
                json={"queryId": str(uuid.uuid4()), "sql": sql, "source": "SqlEditor", "limit": limit},
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "X-Org-ID": self.org_id,
                    "X-Request-ID": str(uuid.uuid4()),
                },
                timeout=self.timeout_s,
            )
            r.raise_for_status()
        except httpx.TimeoutException as e:
            raise ZetarisError(f"Zetaris query timed out after {self.timeout_s:.0f} s") from e
        except httpx.HTTPStatusError as e:
            raise ZetarisError(f"Zetaris HTTP {e.response.status_code}: {e.response.text[:300]}") from e
        except httpx.HTTPError as e:
            raise ZetarisError(f"Cannot reach Zetaris at {self.base}: {e}") from e
        out = r.json()
        return (out.get("data") if isinstance(out, dict) else None) or []


class ZetarisStore:
    def __init__(self, sample_mode: bool = False, timeout_s: float = 45.0):
        self.sample_mode = sample_mode
        self._papers: dict[str, Paper] = {}
        self.client = None if sample_mode else ZetarisRestClient(timeout_s)

    def save_papers(self, papers: list[Paper]) -> None:
        if self.sample_mode:
            self._papers.update({p.id: p for p in papers})
            _log("save papers", f"{len(papers)} papers stored (in-memory, sample mode)", f"total {len(self._papers)}")
            return
        raise NotImplementedError("TODO: insert papers into Zetaris (table layout not decided yet)")

    def get_papers(self, paper_ids: list[str] | None = None) -> list[Paper]:
        if self.sample_mode:
            if paper_ids is None:
                papers = list(self._papers.values())
            else:
                papers = [self._papers[i] for i in paper_ids if i in self._papers]
            _log("get papers", f"{len(papers)} papers returned (in-memory, sample mode)",
                 f"years {_year_range(papers)}")
            return papers
        raise NotImplementedError("TODO: query papers from Zetaris with self.query(...)")

    def query(self, sql: str) -> list[list[Any]]:
        """Free-form SQL for agents that need it, e.g. filter by year or citation count."""
        if self.client is None:
            raise ZetarisError("Zetaris SQL is not available in sample mode")
        rows = self.client.run_sql(sql)
        _log("sql query", f"{len(rows)} rows", sql[:300])
        return rows


def _log(action: str, decision: str, result: str) -> None:
    if trace := current_trace():
        trace.log("zetaris", action, decision, result)


def _year_range(papers: list[Paper]) -> str:
    years = [p.year for p in papers if p.year]
    return f"{min(years)}-{max(years)}" if years else "n/a"
