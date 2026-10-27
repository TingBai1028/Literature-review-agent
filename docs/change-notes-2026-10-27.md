# 27 October 2026 change notes: grading recovery and paper-search budgets

The original `grader-fixes` work addressed interrupted analysis and exhausted scholarly-search quotas. Later updates on the same date added bounded stage-grading requests and refreshed the evaluation and test counts.

## 1. Preserve findings when grading fails, and retry missing grades later

**Original problem:** the Connection finder had generated findings, but a timeout or invalid answer from the independent grader marked the whole stage incomplete. Graph 2 then reported `Connections come first` despite a usable Graph 1, and retrying could regenerate existing findings.

**Current behavior:**

- Record a finding stage as complete as soon as its finder finishes. If grading is unavailable, preserve the findings and evidence, mark `<stage>_grade` pending, and allow later finding stages to proceed.
- Produce new findings before retrying older missing grades; one request does not retry indefinitely.
- Versions with pending work run only unfinished steps. Grade-only recovery reuses connections, gaps, original quotes, audits, dependencies and valid grades.
- Support older failed checkpoints that contain pending-grade markers without completed-stage markers.
- Time and token exhaustion still stop execution. Newly completed findings and valid grades are saved in a `partial` child version.
- Source snapshots remain immutable. Replaying a request ID returns the same version without another model call. Complete findings may become active even when only a grade is unavailable.
- Analysis after moving papers follows the same grading-failure rules.

Implementation and operating details: [grounded-findings.md](grounded-findings.md).

## 2. Support a daily budget of approximately 100 ordinary paper searches

**Original problem:** each candidate gap issued a separate scholarly search; rewritten gaps could repeat queries. Other candidates continued contacting the provider after a daily-quota response.

**Current behavior:**

- Cache successful OpenAlex queries in local SQLite for 24 hours by default. Retrieval and gap coverage can reuse the results across runs.
- Query text, filters and requested fields must match. A sufficiently large cached result page can serve a smaller request. Failed responses are never cached as an empty literature result.
- Reserve daily quota before every new OpenAlex HTTP attempt, including retries. Threads and processes sharing the database use the same cap.
- Concurrent identical queries share one result; different queries can still run in parallel.
- Each Gap finder invocation has a separate default budget of 10 new coverage requests, shared across clusters, rewrites and fallback providers. Cache hits do not consume that budget.
- A daily-limit response creates a persistent pause until the provider's reset time; valid cached results remain readable.
- When a Semantic Scholar key is configured, use it only after OpenAlex fails.
- Candidates exceeding the budget remain explicitly `unavailable`, with a reason. An unavailable search does not establish novelty.
- OpenAlex's page size is capped at 100.

These defaults apply without editing `.env`:

```dotenv
OPENALEX_DAILY_SEARCH_LIMIT=100
OPENALEX_SEARCH_CACHE_TTL_S=86400
GAP_COVERAGE_MAX_REQUESTS=10
```

The local daily counter resets at midnight UTC. It does not include other programs' or websites' requests, so the provider may reject requests earlier. These values are configurable. The 10-request coverage budget is an engineering default, not an experimentally optimized search strategy.

Full details: [search-budget.md](search-budget.md).

## 3. Validation

| Check | Result | Scope |
| --- | --- | --- |
| Current full automated suite | **485 passed in 11.45 s**, `python -m pytest -q` | Rerun on 27 October after the grading-size fix; no real model calls; supersedes the earlier 442-test recovery-note count |
| Real 50-paper recovery | **7 connections, 31 candidate research gaps**, final status `done`, no pending grades | Resumed a failed checkpoint without rerunning retrieval or clustering |
| Real recovery integrity | 17/17 passed | Preserved original quotes, snapshots, vectors, audits and dependencies; replaying a request added no model call |
| Offline simulation of 31 actual coverage queries | 6/6 passed | 10 fresh requests, 21 deferred; cache-only replay made zero new requests; daily-quota simulation stopped after the first rejected attempt |
| Offline grading-payload replay on another real 50-paper map | All 29 gaps and 87 reviewed pairs preserved once | Compact gap input reduced from 182,169 characters in one payload to at most 34,057 characters per request; no live model or latency measurement |

Reports: [grading recovery](benchmarks/grade-recovery.json), [search budget](benchmarks/search-budget.json), [grading request sizes](benchmarks/grading-payload-size.json). The 31-gap recovery and the 29-gap sizing replay are different saved runs; their counts are not combined.

## 4. Bound oversized stage-grading requests

Previously, the stage grader could still put every gap and repeated source quote into one large request. It now:

- Partitions all accepted findings and reviewed abstentions into batches of at most 5 units and 48,000 serialized user-payload characters.
- Includes only the sources relevant to each batch, deduplicates original quotes, and sends coverage-hit metadata instead of full external paper records. Coverage status and quoted counterevidence remain visible.
- Preserves exact evidence rather than shortening it to fit. A single item exceeding the limit leaves the grade pending before any request is sent.
- Records a complete stage grade only after every batch succeeds. The lowest-scoring batch supplies the stage scores and fix; failing batches cannot be averaged into a pass.
- Checks the existing deadline between batches; all calls still use the run's token meter. A failed batch leaves findings intact and the grade pending for explicit recovery.

Nine new tests cover request sizes, complete item coverage, source fidelity, abstention scope, conservative grading, failed-batch recovery and deadlines. Models, concurrency and model timeouts are unchanged. This fixes the unbounded-input path; it is not a claim that provider latency or all timeouts are solved.

## 5. Remaining limits and submission evidence

- Fifteen historical gap coverage checks remain unavailable. The other sixteen only mean no addressing paper was found in the checked sources.
- No scheduled coverage backfill or coverage-only endpoint was added. Saved versions are not rewritten automatically.
- Independent grades are model judgments. The 31 gaps remain candidate hypotheses requiring scholarly review.
- The first real recovery response used 412,398 tokens against a 350,000-token request budget; usage was known after the response. The agent saved the findings and stopped. The later grade-only request used 13,784 tokens without rerunning a finder.
- More small grading requests can increase overhead. Payload sizes were verified offline; live latency after this change has not been benchmarked.
- The submission video should show a real Graph 2 gap, both source quotes and its bounded coverage status. The final hosted video link remains a submission item.
- API keys, `.env`, raw logs and model caches remain local. The repository contains code, example configuration and compact validation reports.
