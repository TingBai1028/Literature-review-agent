"""Zetaris: shared paper data layer.

The Retriever writes each run's papers to our own Postgres paper store (docker-compose.yml), which
Zetaris has registered as the `litagent_db` data source (scripts/setup_zetaris.py). Every later
agent reads papers back through Zetaris SQL, so all agents work from one source of truth, and a
later version can join a user's own library in the same query.

Zetaris runs locally in Docker. Settings (names from
https://github.com/zetaris/getting-started/blob/main/.env.example):
ZETARIS_REST_URL (default http://localhost:8888/api/v1.0), ZETARIS_ORG_ID, ZETARIS_API_KEY,
plus PAPERS_DB_URL for our paper store. From inside our container, use host.docker.internal.

If the paper store or Zetaris fails during a run, the store falls back to the in-memory copy of the
papers it was given, records why in `fallback_reason` (the orchestrator turns it into a warning),
and logs it, so one sponsor outage doesn't break the run. In sample mode only the in-memory copy is used.

TODO (stretch goal): join the user's own library (uploaded PDFs / reference export) as a second source.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any

import httpx

from litagent.schemas import Paper
from litagent.trace import current_trace

DEFAULT_REST_URL = "http://localhost:8888/api/v1.0"
DATASOURCE = "litagent_db"  # name of our paper store in Zetaris
TABLE = "papers"
COLUMNS = ("id", "title", "abstract", "year", "authors", "citation_count", "is_review", "is_open_access",
           "pdf_url", "doi", "source", "full_text")
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS papers (
    run_id TEXT NOT NULL,
    rank INTEGER NOT NULL,
    id TEXT NOT NULL,
    title TEXT NOT NULL,
    abstract TEXT,
    year INTEGER,
    authors TEXT,             -- JSON list
    citation_count INTEGER,
    is_review BOOLEAN,
    is_open_access BOOLEAN,
    pdf_url TEXT,
    doi TEXT,
    source TEXT NOT NULL,
    full_text TEXT,
    saved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, id)
)"""
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


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


class PaperDB:
    """Write side: our Postgres paper store. Reads go through Zetaris, not through this class."""

    def __init__(self, url: str | None = None, timeout_s: int = 10):
        self.url = url or os.getenv("PAPERS_DB_URL")
        if not self.url:
            raise ZetarisError("Set PAPERS_DB_URL (see .env.example and docker-compose.yml), or run with SAMPLE_MODE=true.")
        self.timeout_s = timeout_s

    def _connect(self):
        import psycopg  # only needed outside sample mode

        return psycopg.connect(self.url, connect_timeout=self.timeout_s,
                               options=f"-c statement_timeout={self.timeout_s * 1000}")

    def create_table(self) -> None:
        with self._connect() as conn:
            conn.execute(CREATE_TABLE_SQL)

    def replace_run(self, run_id: str, papers: list[Paper]) -> None:
        """The run's paper set is replaced, so a re-plan doesn't mix in papers from the previous attempt."""
        rows = [(run_id, rank, *_paper_values(p)) for rank, p in enumerate(papers)]
        placeholders = ", ".join(["%s"] * (2 + len(COLUMNS)))
        with self._connect() as conn:
            conn.execute("DELETE FROM papers WHERE run_id = %s", (run_id,))
            with conn.cursor() as cur:
                cur.executemany(f"INSERT INTO papers (run_id, rank, {', '.join(COLUMNS)}) VALUES ({placeholders})", rows)

    def delete_run(self, run_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM papers WHERE run_id = %s", (run_id,))


class ZetarisStore:
    def __init__(self, sample_mode: bool = False, timeout_s: float = 45.0, run_id: str = "default"):
        if not _SAFE_RUN_ID.match(run_id):
            raise ZetarisError(f"Unsafe run_id for SQL: {run_id!r}")
        self.sample_mode = sample_mode
        self.run_id = run_id
        self.fallback_reason: str | None = None  # set when Zetaris or the paper store failed during this run
        self._papers: dict[str, Paper] = {}  # in-memory copy: sample mode, and the fallback
        self.client = None if sample_mode else ZetarisRestClient(timeout_s)
        self.db = None if sample_mode else PaperDB()

    def save_papers(self, papers: list[Paper]) -> None:
        self._papers = {p.id: p for p in papers}
        if self.sample_mode:
            _log("save papers", f"{len(papers)} papers stored (in-memory, sample mode)", f"total {len(self._papers)}")
            return
        if self.fallback_reason:
            _log("save papers", f"{len(papers)} papers kept in memory", "", "fallback still active")
            return
        try:
            self.db.replace_run(self.run_id, papers)
        except Exception as e:  # psycopg errors and network errors alike: fall back, don't fail the run
            self._fall_back(f"paper store write failed: {type(e).__name__}: {e}")
            return
        _log("save papers", f"{len(papers)} papers written to the paper store", f"{DATASOURCE}.{TABLE}, run_id={self.run_id}")

    def get_papers(self, paper_ids: list[str] | None = None) -> list[Paper]:
        if self.sample_mode or self.fallback_reason:
            papers = self._from_memory(paper_ids)
            how = "in-memory, sample mode" if self.sample_mode else "in-memory fallback"
            _log("get papers", f"{len(papers)} papers returned ({how})", f"years {_year_range(papers)}")
            return papers
        sql = select_papers_sql(self.run_id, paper_ids)
        try:
            rows = self.client.run_sql(sql)
        except ZetarisError as e:
            self._fall_back(f"Zetaris read failed: {e}")
            return self._from_memory(paper_ids)
        papers = [row_to_paper(r) for r in rows]
        _log("sql query", f"{len(rows)} rows -> {len(papers)} papers", sql[:300], why=f"years {_year_range(papers)}")
        return papers

    def query(self, sql: str) -> list[list[Any]]:
        """Free-form SQL for agents that need it, e.g. filter by year or citation count."""
        if self.client is None:
            raise ZetarisError("Zetaris SQL is not available in sample mode")
        rows = self.client.run_sql(sql)
        _log("sql query", f"{len(rows)} rows", sql[:300])
        return rows

    def _from_memory(self, paper_ids: list[str] | None) -> list[Paper]:
        if paper_ids is None:
            return list(self._papers.values())
        return [self._papers[i] for i in paper_ids if i in self._papers]

    def _fall_back(self, reason: str) -> None:
        self.fallback_reason = reason
        if trace := current_trace():
            trace.log("zetaris", "fallback", "use in-memory papers", next_step="continue run", why=reason)


def select_papers_sql(run_id: str, paper_ids: list[str] | None = None) -> str:
    if not _SAFE_RUN_ID.match(run_id):
        raise ZetarisError(f"Unsafe run_id for SQL: {run_id!r}")
    sql = f"SELECT {', '.join(COLUMNS)} FROM {DATASOURCE}.{TABLE} WHERE run_id = '{run_id}'"
    if paper_ids is not None:
        sql += " AND id IN (" + (", ".join(_quote(i) for i in paper_ids) or "NULL") + ")"
    return sql + " ORDER BY rank"


def row_to_paper(row: list[Any]) -> Paper:
    """Zetaris returns every value as text (or None); turn a row back into a Paper."""
    v = dict(zip(COLUMNS, row))
    return Paper(
        id=v["id"],
        title=v["title"] or "",
        abstract=_text(v["abstract"]),
        year=_int(v["year"]),
        authors=json.loads(v["authors"]) if _text(v["authors"]) else [],
        citation_count=_int(v["citation_count"]),
        is_review=_bool(v["is_review"]),
        is_open_access=bool(_bool(v["is_open_access"])),
        pdf_url=_text(v["pdf_url"]),
        doi=_text(v["doi"]),
        source=v["source"],
        full_text=_text(v["full_text"]),
    )


def _paper_values(p: Paper) -> tuple:
    return (p.id, p.title, p.abstract, p.year, json.dumps(p.authors, ensure_ascii=False), p.citation_count,
            p.is_review, p.is_open_access, p.pdf_url, p.doi, p.source, p.full_text)


def _quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def _int(value: Any) -> int | None:
    return None if value in (None, "") else int(value)


def _bool(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    return str(value).strip().lower() in ("true", "t", "1")


def _log(action: str, decision: str, result: str, next_step: str = "", why: str = "") -> None:
    if trace := current_trace():
        trace.log("zetaris", action, decision, result, next_step, why)


def _year_range(papers: list[Paper]) -> str:
    years = [p.year for p in papers if p.year]
    return f"{min(years)}-{max(years)}" if years else "n/a"
