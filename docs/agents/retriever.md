# 2. Retriever agent

Code: `litagent/agents/retriever.py` · Tools: `litagent/tools/`

1. **Goal:** Find the papers that match the search plan and store them in Zetaris.
2. **Plan:**
   1. Run each query on OpenAlex, one request per query (TODO: Semantic Scholar, arXiv). A failed query is logged and skipped; if every query fails the run stops with an error.
   2. Open-access only unless the user is signed in with a school account.
   3. Merge and remove duplicates (same DOI or same normalised title, which also catches preprint + published version). Drop papers without an abstract: later agents quote abstracts as evidence.
   4. Rank 70% relevance (reciprocal rank fusion across queries) / 30% citations per year (`rank_relevance_weight` in config), then cut to the effort level's paper limit.
   5. High / Ultra: download full-text PDFs (TODO; logged as skipped for now).
3. **Tools:**
   - `search_openalex` → query, criteria → `list[Paper]` → retries network errors, 5xx and short 429s 3×, then raises `OpenAlexError`; fails at once when the daily limit is used up (a free `OPENALEX_API_KEY` raises it 10×)
   - `search_semantic_scholar` → TODO
   - `search_arxiv` → TODO
4. **Memory to keep:** writes papers to Zetaris; adds paper nodes to the world model.
5. **Rubric:** no grading agent (team decision). Checked by Human review 1.
6. **Stop conditions:** zero papers found → status `no_results` with a message naming the filters and suggesting broader terms.
7. **Run log:** papers per query, failed queries, duplicates removed, papers without abstract, citation filter, final count; LLM summary fallback.
8. **Guardrails:** respect API rate limits; no paywalled downloads without a licence check.

**Open question:** institutional access via school login. Check the university's licence terms (publishers usually forbid automated bulk downloading). Safer alternative: signed-in users upload PDFs they already have.

**Input:** `SearchPlan` · **Output:** `list[Paper]`, `RetrievalSummary`
**Owner:** TODO · **Status:** OpenAlex working (mocked tests + one live check); LLM summary not yet tried on Nightshift; Semantic Scholar, arXiv, full text TODO
