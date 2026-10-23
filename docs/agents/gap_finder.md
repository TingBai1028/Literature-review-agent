# 5. Gap finder agent

Code: `litagent/agents/gap_finder.py` · Prompt: `prompts/gap_finder.md`

1. **Goal:** Find research gaps inside each cluster, backed by evidence, to help researchers find novelty.
2. **Plan:**
   1. In each cluster, pick paper pairs whose similarity falls in a set range (TODO: tune, draft 0.5–0.8).
   2. Ask the LLM what is missing between them, with quotes.
   3. Run a quick targeted search to check the gap isn't already covered.
   4. Write gaps to the world model.
3. **Tools:** LLM; `search_openalex` for the coverage check.
4. **Memory to keep:** gaps → world model.
5. **Rubric:** see `prompts/grader.md` → gaps.
6. **Stop conditions:** grade < 7/9 → redo once with the fix → continue with a warning.
7. **Run log:** candidate gaps, gaps dropped by the coverage check and why.
8. **Guardrails:** cap gaps per cluster (TODO number).

**Input:** papers, clusters, connections · **Output:** `list[Gap]`
**Owner:** TODO · **Status:** Dry run only
