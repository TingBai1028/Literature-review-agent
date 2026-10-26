# Agent name

Agent Loop Spec from the Day 4 workshop. Copy this file for a new agent.

1. **Goal:** One sentence.
2. **Plan (≤5 steps):** label each step `[code]` (deterministic) or `[LLM]` (model call); the trace's `step_kind` says the same.
   1. `[code]` or `[LLM]` ...
3. **Tools (name → inputs → output → fail mode):**
   - `tool_name` → inputs → output → what happens when it fails
4. **Memory to keep:** What it reads from / writes to Zetaris and the Meterless world model.
5. **Rubric (0–3 × 3):** accuracy · appropriateness · actionability. What each means for this agent.
6. **Stop conditions:** e.g. score < 7/9 → one fix, redo once → warn or ask the user.
7. **Run log:** step · decision · result · next · why (written by `litagent/trace.py`), streamed live as progress events (`docs/events.md`).
8. **Guardrails:** Cap steps, tool calls and tokens; hard stops; always log why.

**Input contract:** schema in `litagent/schemas.py`
**Output contract:** schema in `litagent/schemas.py`
**Owner:** who builds and maintains it
**Status:** Not started / Sample mode only / Working / Tested
