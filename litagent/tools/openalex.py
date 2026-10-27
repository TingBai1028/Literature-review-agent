"""OpenAlex search tool. Docs: https://docs.openalex.org

name: search_openalex
inputs: query, SearchCriteria, limit, open_access_only
output: list[Paper], in OpenAlex relevance order (one request per query)
fail mode: network error, 5xx or a short 429 -> retry up to 3 times with backoff, then raise OpenAlexError.
           Daily budget used up (429 with a long wait) or a 4xx -> raise OpenAlexError at once:
           retrying can't help, and a run must not wait hours.

Usage is metered per day: about 100 searches without a key, 10x that with a free OPENALEX_API_KEY.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import threading
import time

import httpx

from litagent.config import Settings
from litagent.cancellation import cancellable_sleep, check_cancelled
from litagent.schemas import Paper, SearchCriteria
from litagent.tools.search_store import SearchBudget, SearchLimitError, SearchStore
from litagent.trace import current_trace

BASE_URL = "https://api.openalex.org/works"
TIMEOUT_S = 30
MAX_PER_PAGE = 100
MAX_WAIT_S = 5  # a 429 asking us to wait longer than this means the daily budget is used up
FIELDS = ("id,doi,display_name,publication_year,type,cited_by_count,open_access,authorships,abstract_inverted_index,"
          "referenced_works,referenced_works_count")
# Leave out works that aren't papers (datasets, errata, paratext, ...)
TYPE_FILTER = {
    "both": "article|preprint|review",
    "review": "review",
    "primary": "article|preprint",
}


class OpenAlexError(RuntimeError):
    pass


_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def search_openalex(query: str, criteria: SearchCriteria, limit: int = 25, open_access_only: bool = True,
                   *, timeout_s: float = TIMEOUT_S, attempts: int = 3,
                   request_budget: SearchBudget | None = None, settings: Settings | None = None) -> list[Paper]:
    cfg = settings or Settings()
    if cfg.openalex_daily_search_limit < 0 or not math.isfinite(cfg.openalex_search_cache_ttl_s) or cfg.openalex_search_cache_ttl_s < 0:
        raise ValueError("OpenAlex search allowance and cache TTL must be non-negative")
    params = build_params(query.strip(), criteria, limit, open_access_only)
    # Search results are public. Neither credentials nor the user's email are persisted.
    public = {k: v for k, v in params.items() if k not in {"api_key", "mailto", "per-page"}}
    key = hashlib.sha256(json.dumps([BASE_URL, public], sort_keys=True).encode()).hexdigest()
    scope = hashlib.sha256((os.getenv("OPENALEX_API_KEY") or "anonymous").encode()).hexdigest()
    with _locks_guard:
        lock = _locks.setdefault(str(cfg.scholarly_search_db) + key, threading.Lock())
    try:
        store = SearchStore(cfg.scholarly_search_db)
        # Identical requests from parallel clusters share one HTTP response. Different queries can overlap.
        with lock:
            cached = store.get(key, params["per-page"], cfg.openalex_search_cache_ttl_s)
            if cached:
                data, fetched = cached
                if trace := current_trace():
                    trace.log("openalex", "search cache", "hit", result={"fetched_at": fetched},
                              why="Reused the same query/filters and a sufficient result page; no HTTP request")
            else:
                data = _get_with_retry(BASE_URL, params, attempts, timeout_s, store=store, scope=scope,
                                       daily_limit=cfg.openalex_daily_search_limit, request_budget=request_budget)
                store.put(key, params["per-page"], data)
    except (SearchLimitError, OSError, sqlite3.Error) as error:
        raise OpenAlexError(str(error)) from error
    return [_to_paper(w) for w in data.get("results", [])]


def build_params(query: str, criteria: SearchCriteria, limit: int, open_access_only: bool) -> dict:
    types = set(criteria.paper_types)
    kind = "review" if types == {"review"} else "primary" if types == {"primary"} else "both"
    filters = [f"type:{TYPE_FILTER[kind]}"]
    if criteria.year_from:
        filters.append(f"from_publication_date:{criteria.year_from}-01-01")
    if criteria.year_to:
        filters.append(f"to_publication_date:{criteria.year_to}-12-31")
    if criteria.min_citations:
        filters.append(f"cited_by_count:>{criteria.min_citations - 1}")
    if open_access_only:
        filters.append("is_oa:true")

    params = {"search": query, "filter": ",".join(filters), "per-page": min(limit, MAX_PER_PAGE), "select": FIELDS}
    if key := os.getenv("OPENALEX_API_KEY"):
        params["api_key"] = key
    elif email := os.getenv("OPENALEX_EMAIL"):
        params["mailto"] = email
    return params


def _get_with_retry(url: str, params: dict, attempts: int = 3, timeout_s: float = TIMEOUT_S, *,
                    store: SearchStore | None = None, scope: str = "", daily_limit: int = 100,
                    request_budget: SearchBudget | None = None) -> dict:
    problem = ""
    for i in range(attempts):
        check_cancelled()
        if store is not None:
            store.reserve(scope, daily_limit, request_budget)
        try:
            r = httpx.get(url, params=params, timeout=timeout_s)
        except httpx.HTTPError as e:
            problem = f"network error: {type(e).__name__}"
        else:
            if r.status_code == 429:
                wait = _seconds_to_wait(r)
                if wait > MAX_WAIT_S:
                    if store is not None:
                        store.block(scope, wait, "OpenAlex daily limit reached")
                    raise OpenAlexError(
                        f"OpenAlex daily limit reached (resets in {wait / 3600:.1f} h). "
                        "A free OPENALEX_API_KEY raises the limit 10x."
                    )
                problem = "rate limited"
                cancellable_sleep(wait)
                continue
            if r.status_code >= 500:
                problem = f"HTTP {r.status_code}"
            elif r.is_error:  # our request is wrong; retrying won't help
                raise OpenAlexError(f"OpenAlex rejected the request: HTTP {r.status_code} {r.text[:200]}")
            else:
                return r.json()
        if i < attempts - 1:
            cancellable_sleep(2**i)
    raise OpenAlexError(f"OpenAlex failed after {attempts} attempts ({problem})")


def _seconds_to_wait(r: httpx.Response) -> float:
    if r.headers.get("x-ratelimit-remaining") == "0":
        try:
            wait = float(r.headers.get("x-ratelimit-reset") or 86_400)
            if wait > 1_000_000_000:  # some providers report a Unix timestamp, others seconds remaining
                wait -= time.time()
            return max(0.0, wait) if math.isfinite(wait) else 86_400
        except ValueError:
            return 86_400
    try:
        return float(r.headers.get("retry-after") or 1)
    except ValueError:
        return 1.0


def _to_paper(work: dict) -> Paper:
    oa = work.get("open_access") or {}
    return Paper(
        id=work["id"].rsplit("/", 1)[-1],
        title=work.get("display_name") or "",
        abstract=_rebuild_abstract(work.get("abstract_inverted_index")),
        year=work.get("publication_year"),
        authors=[a["author"]["display_name"] for a in work.get("authorships") or [] if a.get("author")],
        citation_count=work.get("cited_by_count"),
        is_review=work.get("type") == "review",
        is_open_access=bool(oa.get("is_oa")),
        pdf_url=oa.get("oa_url"),
        doi=work.get("doi"),
        source="openalex",
        # An empty list usually means OpenAlex has no reference data, not that the paper cites nothing.
        references=[w.rsplit("/", 1)[-1] for w in work["referenced_works"]] if work.get("referenced_works") else None,
        reference_count=work.get("referenced_works_count"),
    )


def _rebuild_abstract(inverted_index: dict | None) -> str | None:
    """OpenAlex stores abstracts as {word: [positions]}; turn it back into text."""
    if not inverted_index:
        return None
    positions = [(pos, word) for word, poss in inverted_index.items() for pos in poss]
    return " ".join(word for _, word in sorted(positions))
