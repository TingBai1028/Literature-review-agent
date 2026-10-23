# 3. Clusterer agent

Code: `litagent/agents/clusterer.py` · Prompt: `prompts/cluster_labeler.md`

1. **Goal:** Group papers into labelled research ideas.
2. **Plan:**
   1. Build text per paper: metadata (Normal / Medium) or full text (High / Ultra, via Meterless Markovian engine).
   2. Embed each paper.
   3. Group papers with cosine similarity ≥ 0.7.
   4. Label each group with the LLM.
   5. Write clusters to the world model.
3. **Tools:** embedding model (TODO: choose, e.g. SPECTER2), `group_by_threshold` (written), LLM labeller.
4. **Memory to keep:** clusters → world model.
5. **Rubric:** see `prompts/grader.md` → clusters. Rule-based size check runs first (no cluster > 40% of papers, ≤ 50% single-paper clusters).
6. **Stop conditions:** grade < 7/9 → redo once with the grader's fix → continue with a warning.
7. **Run log:** threshold used, number of clusters, size distribution.
8. **Guardrails:** TODO.

**Research TODO:** confirm the 0.7 threshold for the chosen embedding model; decide what to do with single-paper outliers (they may be useful to the Gap finder).

**Input:** `list[Paper]`, Effort · **Output:** `list[Cluster]`
**Owner:** TODO · **Status:** Dry run only
