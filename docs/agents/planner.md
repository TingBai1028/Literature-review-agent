# 1. Planner agent

Code: `litagent/agents/planner.py` · Prompt: `prompts/planner.md`

1. **Goal:** Turn the user's question and effort level into a search plan the Retriever can run.
2. **Plan:**
   1. `[LLM]` Check there is a clear literature topic (examples in the prompt; an empty message is caught in `[code]`); if not, ask the user in a friendly way.
   2. `[LLM]` Extract stated criteria: years, citations, primary vs review. A citation minimum is set only when the user gives a number; otherwise the Retriever ranks by citations per year.
   3. `[code]` Fill missing criteria with defaults (both paper types; no start year, so classic papers stay searchable).
   4. `[LLM]` Write search queries; `[code]` fixes how many: Fast 3, Pro 5 (older levels: Normal 2, Medium 3, High/Ultra 4; `num_queries` in `EFFORT_PROFILES`).
   5. `[code]` Set paper limit and token budget from the effort level.
3. **Tools:** none (LLM only).
4. **Memory to keep:** user feedback from Human review 1 and 2, so a re-plan changes only what the user asked to change. The feedback and the previous plan are passed in the re-plan request itself. Nothing is kept in Nightshift's answer memory (H-MEM): every model call gets a fresh scope, so earlier answers can't leak into a new plan (`litagent/integrations/llm.py`).
5. **Rubric:** no grading agent (see ARCHITECTURE.md): Human review 1 judges the plan by the papers it finds. Success = the plan runs in the Retriever without errors. Code checks: an `ok` plan has a topic and at least one query; `need_topic` has a message (failures are retried once with the error, and an answer that only repeats the request is sent again).
6. **Stop conditions:** no topic → stop and ask the user. Re-plans capped at `max_replans` (3).
7. **Run log:** logs the plan, the Planner's one-sentence rationale and which defaults were used; `start` and `done` progress events.
8. **Guardrails:** never invent a topic. Tokens: the run's budget (`EFFORT_PROFILES`) is checked before every call; one planner call uses about 2–3k tokens (24 Oct traces: 1.9–2.8k prompt, 105–165 completion).

**Input:** question (str), Effort, optional feedback + previous plan (on a re-plan) · **Output:** `PlannerResult`
**Owner:** Ting Bai and Xin Tian · **Status:** Working on Nightshift (Nemotron 3 Ultra) and in tests with the LLM mocked (`tests/test_planner.py`). Real runs on 27 Oct showed the model sometimes repeating the request instead of planning; the closing no-echo line in every system message fixed it (10 of 10 plans on the question that failed).
