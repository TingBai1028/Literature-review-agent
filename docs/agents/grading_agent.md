# Grading agent

Code: `litagent/agents/grader.py` · Prompt: `prompts/grader.md`

1. **Goal:** Check the Clusterer, Connection finder and Gap finder before their output moves on.
2. **Plan:**
   1. Run cheap rule-based checks first (cluster sizes).
   2. Score the output against the source papers with the stage's rubric.
   3. Pass at 7/9; otherwise return exactly one fix.
3. **Tools:** LLM.
4. **Memory to keep:** grades go in the run log only.
5. **Rubric (0–3 × 3):** accuracy · appropriateness · actionability, with stage-specific details in the prompt.
6. **Stop conditions:** each stage gets one redo (`max_redo_per_stage`), then continues with a warning. TODO: or ask the user?
7. **Run log:** score per criterion, pass/fail, fix.
8. **Guardrails:** sees the output and the evidence, not the producing agent's reasoning. TODO: try a different model from the producing agents.

**Input:** stage, output, papers · **Output:** `Grade`
**Owner:** TODO · **Status:** Sample mode + size check written
