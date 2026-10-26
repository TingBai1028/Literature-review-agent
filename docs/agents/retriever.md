# 2. Retriever agent

Code: `litagent/agents/retriever.py` · Tools: `litagent/tools/`

1. **Goal:** Find the papers that match the search plan and store them in Zetaris.
2. **Plan:**
   1. `[code]` Run each query on every configured source (`retrieval_sources`: OpenAlex and arXiv by default, plus Semantic Scholar when `SEMANTIC_SCHOLAR_API_KEY` is set), open-access only unless the user is signed in with a school account. A failed search is logged and skipped; if every search fails the run stops with an error. Each search sends a progress event with the running paper count.
   2. `[code]` Merge and remove duplicates across sources and versions (same DOI, same arXiv ID, including arXiv DOIs `10.48550/arXiv.*`, or same normalised title). The first-seen record keeps its ID; missing abstract/DOI/PDF link are filled from its duplicates and the highest citation count is kept. Then drop papers without an abstract: later agents quote abstracts as evidence. A stated citation minimum also drops records with no citation count (arXiv).
   3. `[code]` Relevance floor: embed the question and each paper's title + first 600 abstract characters with the clustering model and drop papers below cosine 0.5 (`retrieval_similarity_min`, same scale as the Clusterer's main gate). Without a local embedding model the floor is skipped (logged) and search-rank fusion is used instead.
   4. `[code]` Keep the most relevant papers up to the effort level's limit, then order them 70% relevance / 30% citations per year (`rank_relevance_weight`). Citations only reorder the chosen papers; they never bring in an off-topic one. Fewer papers than the limit is normal when few are relevant.
   5. `[code]` High / Ultra: download open-access full-text PDFs; papers without one keep their abstract. `[LLM]` Summarise the set for Human review 1 (plain summary if the call fails).
3. **Tools:**
   - `search_openalex` → query, criteria → `list[Paper]` → retries network errors, 5xx and short 429s 3×, then raises `OpenAlexError`; fails at once when the daily limit is used up (a free `OPENALEX_API_KEY` raises it 10×)
   - `search_semantic_scholar` → query, criteria → `list[Paper]` (`S2:<id>`) → retries 5xx and short 429s, then raises `SemanticScholarError`; year, citation-minimum and OA filters server-side, paper type filtered from `publicationTypes`
   - `search_arxiv` → query, criteria → `list[Paper]` (`arXiv:<id>`, PDF link always set, no citation count) → requests spaced 3 s apart as arXiv asks; retries 5xx, then raises `ArxivError`; skipped for reviews-only plans. arXiv ANDs every word, so when fewer than 25 papers match all words, papers matching any word top the list up (the relevance floor removes the off-topic ones)
4. **Memory to keep:** writes papers to Zetaris; adds paper nodes to the world model.
5. **Rubric:** no grading agent (team decision). Checked by Human review 1.
6. **Stop conditions:** zero papers found → status `no_results` with a message naming the filters and suggesting broader terms.
7. **Run log:** papers per query, failed queries, duplicates removed, papers without abstract, citation filter, papers below the relevance floor and scoring time, final count; LLM summary fallback.
8. **Guardrails:** respect API rate limits; no paywalled downloads without a licence check.

**Open question:** institutional access via school login. Check the university's licence terms (publishers usually forbid automated bulk downloading). Safer alternative: signed-in users upload PDFs they already have.

**Input:** `SearchPlan` · **Output:** `list[Paper]`, `RetrievalSummary`
**Owner:** TODO · **Status:** OpenAlex, arXiv and Semantic Scholar working (mocked tests; live checks 26 Oct: OpenAlex and arXiv returned results, keyless Semantic Scholar returned 429); LLM summary checked on Nightshift; web Human review 1 via `POST /search`
