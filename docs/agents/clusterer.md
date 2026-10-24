# 3. Clusterer agent

Code: `litagent/agents/clusterer.py` · Prompt: `prompts/cluster_labeler.md`

1. **Goal:** Group papers into labelled research ideas.
2. **Plan:**
   1. Build text per paper: title + abstract (full text at High / Ultra is TODO, via the Meterless Markovian engine).
   2. Embed each paper locally (`BAAI/bge-small-en-v1.5` via fastembed; Nightshift serves no embeddings endpoint), then mean-center the run's embeddings so the shared topic doesn't dominate.
   3. Group with average linkage at mean-centered cosine ≥ 0.05 (`cluster_similarity_threshold`, calibrated with `scripts/check_threshold.py`: 6–9 clusters, largest 16–30%, ≤ 1 paper left out on 3 topics × 30/60 papers). Groups smaller than 2 papers are set aside as `unclustered`.
   4. Label every group in one LLM call; groups the labeller calls incoherent become unclustered.
   5. Write clusters and unclustered papers to the world model.
3. **Tools:** `embed` (fastembed), `center`, `average_linkage`, LLM labeller (`prompts/cluster_labeler.md`).
4. **Memory to keep:** clusters → world model.
5. **Rubric:** see `prompts/grader.md` → clusters. Rule-based size check runs first (no cluster > 40% of papers, ≤ 50% single-paper clusters).
6. **Stop conditions:** grade < 7/9 → redo once with the grader's fix (passed to the labeller; "too broad" raises the threshold, "too fragmented" lowers it) → continue with a warning.
7. **Run log:** threshold used, number of clusters, size distribution, unclustered count, embedding time, dropped incoherent groups.
8. **Guardrails:** TODO.

**Live check (24 Oct, 30 real GNN drug-discovery papers):** 5 specific clusters + 3 unclustered in 27 s (embedding 7 s, 1 labelling call).

**Input:** `list[Paper]`, Effort · **Output:** `list[Cluster]`
**Owner:** TODO · **Status:** Working (mocked tests + live check on real papers)
