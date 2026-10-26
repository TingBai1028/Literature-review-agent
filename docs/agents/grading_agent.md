# Grading agent

Code: `litagent/agents/grader.py` · Prompt: `prompts/grader.md`

1. **Goal:** Check the Clusterer, Connection finder and Gap finder before their output moves on.
2. **Plan:**
   1. `[code]` Run cheap checks first: cluster sizes (question maps exempt main and foundation and use side size as a diagnostic); for findings, quotes verbatim in both papers and no gap already filled.
   2. `[LLM]` Score the output against the source papers with the stage's rubric.
   3. `[code]` Pass at 7/9; otherwise the grade must carry exactly one fix (repaired once if missing).
3. **Tools:** LLM.
4. **Memory to keep:** grades are recorded as World Model facts and in the trace.
5. **Rubric (0–3 × 3):** accuracy · appropriateness · actionability, with stage-specific details in the prompt.
6. **Stop conditions:** each stage gets one redo (`max_redo_per_stage`), then continues with a warning. TODO: or ask the user?
7. **Run log:** score per criterion, pass/fail, fix.
8. **Guardrails:** sees the output and the evidence, not the producing agent's reasoning. TODO: try a different model from the producing agents.

Question maps include the research question, cluster roles and selected source evidence.
The producer's per-paper reasons and alternate scores are excluded from the grader input.
Main is judged as the most topic-related cluster, foundation as classic background work, and sides by topic coherence.
`POST /cluster` is a single-pass checkpoint and retains a failed grade with warnings;
full pipeline runs keep their bounded grading retry. A finding grade requested by `/analyze` is not sent again
after a timeout: the grade stays pending and a later analysis request retries it (`retry_timeout=False`).
Each model call uses an isolated
Nightshift H-MEM scope. See [main/side behavior](../main-side-clusters.md).

**Input:** stage, output, papers · **Output:** `Grade`
**Owner:** TODO · **Status:** Source-based grading, size diagnostics, sample mode and World Model recording implemented.

**Explained grades (26 Oct).** A live grader once returned 0/0/0 with empty reasoning and no fix, which
was counted as a failure and triggered an expensive redo. The model's grade is now validated: reasoning
must not be empty and a total below the pass mark needs a concrete fix, otherwise `complete_json` repairs
it once. An **empty** connection/gap output is graded as a claim ("no reviewed pair has a supported
finding"): the payload says so explicitly, and a failing fix must name a reviewed pair and its supporting
abstract statements. Before this, the same honest abstention scored 9/9 in one run and 0/9 in another.

For independent per-claim scoring in the review UI, see the [Review Agent](review_agent.md).
Its model-only reports are separate from these stage grades and from human annotations.
