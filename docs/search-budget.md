# Search policy for a 100-request daily allowance

Implemented 27 Oct 2026. Retrieval and Gap coverage share an OpenAlex response cache and
an atomic daily HTTP-attempt counter. Finding generation, candidate counts, model concurrency
and scientific evidence checks are unchanged.

## Request policy

1. Look up the exact public query, filters and selected fields in the persistent cache first.
   Cached pages expire after 24 hours by default. A larger page can satisfy a smaller request;
   a smaller full page cannot pretend to contain more results. A successful empty page is cached;
   an error is never converted into a successful empty result. Similar wording is not an exact hit.
2. Before each new OpenAlex HTTP attempt, reserve one of the local daily allowances (default 100).
   Retrieval, coverage, HTTP retries and separate application worker processes share this counter.
   It resets at midnight UTC. Calls outside this database, including website use, are not counted here.
3. Each Gap finder invocation additionally permits at most 10 new coverage HTTP attempts, shared
   across its parallel clusters, rewrites and provider fallback. Cache hits do not consume this allowance.
   This is a configurable engineering default, not a measured optimum for discovery quality.
4. A long 429 response pauses future uncached OpenAlex requests until its reset time. The pause
   persists across runs/processes; cached successful results remain usable. Only requests already in
   flight can still return after another worker reports the limit. Transient failures are not paused all day.
5. With a Semantic Scholar key, use it only when OpenAlex fails. Successful OpenAlex results, including
   an empty result, do not automatically trigger another source. Fallback also consumes the coverage allowance.

When no allowance remains, preserve the candidate with `coverage_status="unavailable"` and an
explicit deferred-search reason. It must not become `not_filled` or evidence of novelty. A per-claim
model label or an independent stage grade does not substitute for the missing coverage check.

## Configuration

Defaults already apply without editing `.env`:

```dotenv
OPENALEX_DAILY_SEARCH_LIMIT=100
OPENALEX_SEARCH_CACHE_TTL_S=86400
GAP_COVERAGE_MAX_REQUESTS=10
# Optional location; share this file among workers using the same allowance.
# SCHOLARLY_SEARCH_DB=data/cache/scholarly-search.sqlite3
```

`GAP_COVERAGE_MAX_REQUESTS=0` permits cached OpenAlex results only; no new coverage requests
are issued. `OPENALEX_DAILY_SEARCH_LIMIT=0` similarly allows only cached OpenAlex responses.
The cache contains public result records, timestamps and hashed identities; neither API keys nor
email parameters are stored. This is paper-data caching, independent of Nightshift answer memory.

According to the [OpenAlex cost documentation](https://help.openalex.org/access/example-costs/),
anonymous use has a $0.10/day allowance, roughly 100 ordinary keyword searches. A verified free
key gives $1/day, roughly 1,000 such searches. Other operation types have different prices; reranking
costs extra, and other uses share the same provider budget. These are not universal request counts.
The [authentication reference](https://help.openalex.org/api/authentication/) specifies a maximum
page size of 100; the adapter now uses that limit. Larger pages do not guarantee relevant results.

After configuring a verified key, the local cap can explicitly be raised to 1,000. It stays at 100 by
default even when a key exists. Local counters are conservative attempt counts, not the provider's
credit ledger. Failed HTTP requests may consume a local reservation even if the provider charges nothing.

## Verification and limits

The [offline replay report](benchmarks/search-budget.json) uses all 31 distinct queries from real
saved version `20261026-145411-b427f9`, with HTTP mocked and no LLM calls:

- 10 new successful requests; 21 explicitly deferred.
- Cache-only replay: zero new requests, the same 10 available responses.
- Daily-limit simulation: one HTTP 429, then no requests for the remaining queries.
- Saved real map/state snapshots unchanged.

Tests also exercise concurrent duplicate queries, concurrent daily reservations, UTC reset,
cache expiry, filter isolation, failed-search handling, timeout/retry accounting and provider fallback.
This verifies request accounting and provenance, not semantic coverage quality.

This change does not backfill historical failed checks or add a scheduled background worker.
Already saved findings remain immutable. The allowance is renewed for each explicit Gap finder
invocation, while the daily counter and response cache remain shared. Avoid rerunning discovery
just to refresh coverage; a dedicated coverage-only recovery workflow is a separate next step.

For larger workloads, topic-level shared retrieval pools and local claim checking against the
retrieval backup pool could further reduce calls. Such broader queries change search recall and
need evaluation before replacing the current per-claim queries.
