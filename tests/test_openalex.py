"""OpenAlex tool with HTTP mocked. The fixture is a real (trimmed) /works response."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

from litagent.schemas import SearchCriteria
from litagent.tools import openalex
from litagent.tools.openalex import OpenAlexError, build_params, search_openalex
from litagent.tools.search_store import SearchBudget

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "openalex_works.json").read_text(encoding="utf-8"))


@pytest.fixture
def http(monkeypatch, tmp_path):
    """Queue responses (or exceptions) for httpx.get; records the params of each call and every sleep."""
    state = {"responses": [], "params": [], "sleeps": [], "timeouts": []}

    def fake_get(url, params=None, timeout=None):
        assert 0 < timeout <= openalex.TIMEOUT_S
        state["params"].append(params)
        state["timeouts"].append(timeout)
        item = state["responses"].pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(openalex.httpx, "get", fake_get)
    monkeypatch.setattr(openalex.time, "sleep", state["sleeps"].append)
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    monkeypatch.delenv("OPENALEX_EMAIL", raising=False)
    monkeypatch.setenv("SCHOLARLY_SEARCH_DB", str(tmp_path / "search.sqlite3"))
    monkeypatch.setenv("OPENALEX_DAILY_SEARCH_LIMIT", "100")
    monkeypatch.setenv("OPENALEX_SEARCH_CACHE_TTL_S", "86400")
    return state


def ok():
    return httpx.Response(200, json=FIXTURE)


def filters(params) -> set[str]:
    return set(params["filter"].split(","))


def test_default_filters():
    params = build_params("gnn drug target", SearchCriteria(topic="t", year_from=2021, paper_types=["primary", "review"]), 30, True)
    assert params["search"] == "gnn drug target"
    assert params["per-page"] == 30
    assert "abstract_inverted_index" in params["select"]
    assert filters(params) == {"type:article|preprint|review", "from_publication_date:2021-01-01", "is_oa:true"}


@pytest.mark.parametrize("criteria, expected", [
    ({"paper_types": ["review"]}, "type:review"),
    ({"paper_types": ["primary"]}, "type:article|preprint"),
    ({"paper_types": []}, "type:article|preprint|review"),
    ({"min_citations": 50}, "cited_by_count:>49"),
    ({"year_to": 2015}, "to_publication_date:2015-12-31"),
])
def test_criteria_become_filters(criteria, expected):
    params = build_params("q", SearchCriteria(topic="t", **criteria), 30, True)
    assert expected in filters(params)


def test_signed_in_drops_open_access_filter_and_page_size_is_capped():
    params = build_params("q", SearchCriteria(topic="t"), 500, open_access_only=False)
    assert "is_oa:true" not in filters(params)
    assert params["per-page"] == 100


def test_api_key_preferred_over_email(monkeypatch):
    monkeypatch.setenv("OPENALEX_EMAIL", "me@example.com")
    assert build_params("q", SearchCriteria(topic="t"), 30, True)["mailto"] == "me@example.com"
    monkeypatch.setenv("OPENALEX_API_KEY", "key123")
    params = build_params("q", SearchCriteria(topic="t"), 30, True)
    assert params["api_key"] == "key123" and "mailto" not in params


def test_parses_real_response(http):
    http["responses"] = [ok()]
    papers = search_openalex("gnn", SearchCriteria(topic="t"), 6)
    assert len(papers) == len(FIXTURE["results"]) == 6
    first = papers[0]
    assert first.id.startswith("W")
    assert first.title.startswith("MGraphDTA")
    assert first.doi == "https://doi.org/10.1039/d1sc05180f"
    assert first.abstract and len(first.abstract.split()) > 50
    assert first.authors and first.year == 2022 and first.citation_count == 348
    assert first.source == "openalex"


def test_daily_limit_fails_fast_without_waiting(http):
    http["responses"] = [httpx.Response(429, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "7200"})]
    with pytest.raises(OpenAlexError, match="daily limit"):
        search_openalex("gnn", SearchCriteria(topic="t"))
    assert len(http["params"]) == 1 and http["sleeps"] == []


def test_short_rate_limit_waits_and_retries(http):
    http["responses"] = [httpx.Response(429, headers={"retry-after": "1"}), ok()]
    assert len(search_openalex("gnn", SearchCriteria(topic="t"))) == 6
    assert http["sleeps"] == [1.0]


def test_server_and_network_errors_are_retried(http):
    http["responses"] = [httpx.Response(503), httpx.ConnectTimeout("timeout"), ok()]
    assert len(search_openalex("gnn", SearchCriteria(topic="t"))) == 6
    assert len(http["params"]) == 3


def test_gives_up_after_three_attempts(http):
    http["responses"] = [httpx.Response(500)] * 3
    with pytest.raises(OpenAlexError, match="after 3 attempts"):
        search_openalex("gnn", SearchCriteria(topic="t"))


def test_bad_request_is_not_retried(http):
    http["responses"] = [httpx.Response(400, text="Invalid filter")]
    with pytest.raises(OpenAlexError, match="HTTP 400"):
        search_openalex("gnn", SearchCriteria(topic="t"))
    assert len(http["params"]) == 1


def test_cached_larger_page_is_reused_with_budget_exhausted_and_without_secrets(http, monkeypatch):
    monkeypatch.setenv("OPENALEX_API_KEY", "private-key-never-persist")
    monkeypatch.setenv("OPENALEX_DAILY_SEARCH_LIMIT", "1")
    http["responses"] = [ok()]
    first = search_openalex("gnn", SearchCriteria(topic="t"), 100)
    # A new call/store can serve a smaller page to the Gap finder without using its allowance.
    budget = SearchBudget(0)
    assert search_openalex("gnn", SearchCriteria(topic="t"), 3, request_budget=budget) == first[:3]
    assert budget.used == 0 and len(http["params"]) == 1
    db = Path(openalex.Settings().scholarly_search_db).read_bytes()
    assert b"private-key-never-persist" not in db and b"api_key" not in db


def test_cache_does_not_mix_different_filters_or_short_pages(http):
    http["responses"] = [ok(), ok(), ok()]
    # A full 6-item page cannot satisfy a request for more than 6 results.
    search_openalex("gnn", SearchCriteria(topic="t"), 6)
    search_openalex("gnn", SearchCriteria(topic="t"), 10)
    search_openalex("gnn", SearchCriteria(topic="t", year_from=2024), 10)
    assert len(http["params"]) == 3


def test_empty_success_is_cached_but_a_failed_search_is_not(http):
    http["responses"] = [httpx.Response(503), httpx.Response(200, json={"results": []})]
    with pytest.raises(OpenAlexError):
        search_openalex("q", SearchCriteria(topic="t"), attempts=1)
    assert search_openalex("q", SearchCriteria(topic="t")) == []
    assert search_openalex("q", SearchCriteria(topic="t")) == []
    assert len(http["params"]) == 2


def test_expired_cache_requires_new_request(http, monkeypatch):
    stamp = [100_000.0]
    monkeypatch.setattr(openalex.time, "time", lambda: stamp[0])
    monkeypatch.setenv("OPENALEX_SEARCH_CACHE_TTL_S", "10")
    http["responses"] = [ok(), ok()]
    search_openalex("gnn", SearchCriteria(topic="t"))
    stamp[0] += 11
    search_openalex("gnn", SearchCriteria(topic="t"))
    assert len(http["params"]) == 2


def test_daily_budget_is_atomic_across_parallel_searches_and_resets_utc(http, monkeypatch):
    stamp = [172_800.0]
    monkeypatch.setattr(openalex.time, "time", lambda: stamp[0])
    monkeypatch.setenv("OPENALEX_DAILY_SEARCH_LIMIT", "2")
    http["responses"] = [ok(), ok(), ok()]

    def search(i):
        try:
            return search_openalex(f"query-{i}", SearchCriteria(topic="t"))
        except OpenAlexError as error:
            assert "local daily search budget used" in str(error)
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(search, range(8)))
    assert sum(r is not None for r in results) == len(http["params"]) == 2
    stamp[0] += 86_400
    assert search(8)
    assert len(http["params"]) == 3


def test_same_parallel_query_is_requested_once(http):
    http["responses"] = [ok()]
    budget = SearchBudget(1)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: search_openalex("gnn", SearchCriteria(topic="t"), request_budget=budget), range(4)))
    assert all(r == results[0] for r in results)
    assert len(http["params"]) == budget.used == 1


def test_daily_429_pauses_other_queries_until_reset_but_still_serves_cache(http, monkeypatch):
    stamp = [172_800.0]
    monkeypatch.setattr(openalex.time, "time", lambda: stamp[0])
    http["responses"] = [ok(), httpx.Response(429, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "7200"}), ok()]
    cached = search_openalex("cached", SearchCriteria(topic="t"))
    with pytest.raises(OpenAlexError, match="daily limit"):
        search_openalex("first failure", SearchCriteria(topic="t"))
    with pytest.raises(OpenAlexError, match="cached pause"):
        search_openalex("another query", SearchCriteria(topic="t"))
    assert search_openalex("cached", SearchCriteria(topic="t")) == cached
    assert len(http["params"]) == 2
    stamp[0] += 7201
    assert search_openalex("another query", SearchCriteria(topic="t"))
    assert len(http["params"]) == 3


def test_http_retries_count_against_daily_and_coverage_budgets(http):
    budget = SearchBudget(1)
    http["responses"] = [httpx.Response(503), ok()]
    with pytest.raises(OpenAlexError, match="Coverage search budget used"):
        search_openalex("q", SearchCriteria(topic="t"), request_budget=budget)
    assert len(http["params"]) == budget.used == 1


def test_explicit_settings_control_the_quota(http):
    cfg = openalex.Settings(openalex_daily_search_limit=0)
    with pytest.raises(OpenAlexError, match="local daily search budget used"):
        search_openalex("q", SearchCriteria(topic="t"), settings=cfg)
    assert http["params"] == []


def test_coverage_budget_applies_across_queries_but_allows_cache_hits(http, monkeypatch):
    from litagent.agents.gap_finder import _Run
    from litagent.config import Settings
    from litagent.finding_engine import FindingContext
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    cfg = Settings(gap_coverage_max_requests=2)
    run = _Run([], {}, None, cfg, FindingContext(deadline=openalex.time.monotonic() + 60))
    http["responses"] = [ok(), ok()]
    assert run._search("first")[0].status == "ok"
    assert run._search("second")[0].status == "ok"
    deferred = run._search("third")[0]
    assert deferred.status == "unavailable" and "external verification deferred" in deferred.error
    assert run._search("first")[0].status == "ok"
    assert len(http["params"]) == run.coverage_budget.used == 2
    assert all(t <= cfg.gap_coverage_timeout_s for t in http["timeouts"])


def test_second_provider_is_only_a_fallback_and_shares_the_coverage_allowance(http, monkeypatch):
    from litagent.agents import gap_finder
    from litagent.config import Settings
    from litagent.finding_engine import FindingContext
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "test")
    fallback_calls = []
    monkeypatch.setattr(gap_finder, "search_semantic_scholar", lambda *a, **kw: fallback_calls.append(a) or [])
    run = gap_finder._Run([], {}, None, Settings(gap_coverage_max_requests=3),
                          FindingContext(deadline=openalex.time.monotonic() + 60))
    http["responses"] = [ok(), httpx.Response(503)]
    assert len(run._search("primary works")) == 1 and fallback_calls == []
    checks = run._search("primary fails")
    assert checks[0].status == "unavailable" and checks[1].status == "ok"
    assert len(fallback_calls) == 1 and run.coverage_budget.used == 3
    assert len(http["params"]) == 2


def test_coverage_call_can_bound_timeout_and_disable_http_retries(http, monkeypatch):
    calls = []
    def fail(url, params, timeout):
        calls.append(timeout)
        raise httpx.ConnectTimeout("bounded coverage request")
    monkeypatch.setattr(openalex.httpx, "get", fail)
    monkeypatch.setattr(openalex.time, "sleep", lambda *a: pytest.fail("One-attempt coverage must not back off"))
    with pytest.raises(OpenAlexError, match="after 1 attempts"):
        search_openalex("positive study", SearchCriteria(topic="coverage"), timeout_s=7.5, attempts=1)
    assert calls == [7.5]
