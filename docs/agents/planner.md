# 1. Planner agent

Code: `litagent/agents/planner.py` · Prompt: `prompts/planner.md`

1. **Goal:** Turn the user's question and effort level into a search plan the Retriever can run.
2. **Plan:**
   1. Check there is a clear literature topic; if not, ask the user in a friendly way.
   2. Extract stated criteria: relevance, years, citations, primary vs review.
   3. Fill missing criteria with defaults (past 5 years, both paper types).
   4. Write 2–4 search queries.
   5. Set paper limit and token budget from the effort level.
3. **Tools:** none (LLM only).
4. **Memory to keep:** user feedback from Human review 1 and 2, so a re-plan changes only what the user asked to change. TODO: store in H-MEM for follow-up sessions?
5. **Rubric:** TODO. Success = the plan runs in the Retriever without errors.
6. **Stop conditions:** no topic → stop and ask the user. Re-plans capped at `max_replans` (3).
7. **Run log:** logs which defaults were used and why.
8. **Guardrails:** never invent a topic. TODO: token cap per call.

**Input:** question (str), Effort, optional feedback · **Output:** `PlannerResult`
**Owner:** TODO · **Status:** Dry run only
