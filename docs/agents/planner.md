# 1. Planner agent

Code: `litagent/agents/planner.py` · Prompt: `prompts/planner.md`

1. **Goal:** Turn the user's question and effort level into a search plan the Retriever can run.
2. **Plan:**
   1. Check there is a clear literature topic (the LLM decides, with examples in the prompt; an empty message is caught in code); if not, ask the user in a friendly way.
   2. Extract stated criteria: years, citations, primary vs review. A citation minimum is set only when the user gives a number; otherwise the Retriever ranks by citations per year.
   3. Fill missing criteria with defaults (past 5 years, both paper types).
   4. Write search queries: Normal 2, Medium 3, High/Ultra 4 (`num_queries` in `EFFORT_PROFILES`).
   5. Set paper limit and token budget from the effort level.
3. **Tools:** none (LLM only).
4. **Memory to keep:** user feedback from Human review 1 and 2, so a re-plan changes only what the user asked to change. TODO: store in H-MEM for follow-up sessions?
5. **Rubric:** TODO. Success = the plan runs in the Retriever without errors. Code checks: an `ok` plan has a topic and at least one query; `need_topic` has a message (failures are retried once with the error).
6. **Stop conditions:** no topic → stop and ask the user. Re-plans capped at `max_replans` (3).
7. **Run log:** logs the plan, the Planner's one-sentence rationale and which defaults were used.
8. **Guardrails:** never invent a topic. TODO: token cap per call.

**Input:** question (str), Effort, optional feedback + previous plan (on a re-plan) · **Output:** `PlannerResult`
**Owner:** TODO · **Status:** Working with the LLM mocked (`tests/test_planner.py`); prompt not yet tuned on Nightshift
