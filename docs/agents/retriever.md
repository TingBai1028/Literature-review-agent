# 2. Retriever agent

Code: `litagent/agents/retriever.py` · Tools: `litagent/tools/`

1. **Goal:** Find the papers that match the search plan and store them in Zetaris.
2. **Plan:**
   1. Run each query on OpenAlex (and TODO: Semantic Scholar, arXiv).
   2. Open-access only unless the user is signed in with a school account.
   3. Remove duplicates (same DOI or title).
   4. Rank and cut to the effort level's paper limit.
   5. High / Ultra: download full-text PDFs.
3. **Tools:**
   - `search_openalex` → query, criteria → `list[Paper]` → retry 3× with backoff, then return []
   - `search_semantic_scholar` → TODO
   - `search_arxiv` → TODO
4. **Memory to keep:** writes papers to Zetaris; adds paper nodes to the world model.
5. **Rubric:** no grading agent (team decision). Checked by Human review 1.
6. **Stop conditions:** zero papers found → TODO: tell the user and suggest broader terms.
7. **Run log:** number of papers per source, duplicates removed.
8. **Guardrails:** respect API rate limits; no paywalled downloads without a licence check.

**Open question:** institutional access via school login. Check the university's licence terms (publishers usually forbid automated bulk downloading). Safer alternative: signed-in users upload PDFs they already have.

**Input:** `SearchPlan` · **Output:** `list[Paper]`, `RetrievalSummary`
**Owner:** TODO · **Status:** OpenAlex drafted, rest TODO
