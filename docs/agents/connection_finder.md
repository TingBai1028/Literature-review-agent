# 4. Connection finder agent

Code: `litagent/agents/connection_finder.py` · Prompt: `prompts/connection_finder.md`

1. **Goal:** Explain how papers relate, within each cluster and between clusters, with evidence.
2. **Plan:**
   1. Within each cluster, choose paper pairs to compare (TODO: all pairs or top-k most similar).
   2. Ask the LLM how each pair connects, with a quote from each paper.
   3. Between clusters, compare cluster summaries or representative papers.
   4. Write connections to the world model.
3. **Tools:** LLM; optional `get_citations` (Semantic Scholar) as extra evidence.
4. **Memory to keep:** connections → world model (edges in the paper map).
5. **Rubric:** see `prompts/grader.md` → connections.
6. **Stop conditions:** grade < 7/9 → redo once with the fix → continue with a warning.
7. **Run log:** pairs compared, connections kept vs dropped.
8. **Guardrails:** cap pairs per cluster (TODO number) so cost doesn't grow with n².

**Research TODO:** which connection types to show (builds on, same method / different data, same question / different method, ...).

**Input:** papers, clusters · **Output:** `list[Connection]`
**Owner:** TODO · **Status:** Dry run only
