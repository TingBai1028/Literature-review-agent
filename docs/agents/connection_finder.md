# 4. Connection finder agent

Code: `litagent/agents/connection_finder.py`, `litagent/finding_engine.py`.
Prompts: `prompts/connection_finder.md`, `prompts/connections_verify.md`.

**Status:** Real source-grounded implementation plus offline sample branch.

## Agent Loop Spec

1. **Goal:** Link papers (never clusters) with edges a human can read: a relation type, a one-sentence reason, a longer reason and the evidence it rests on.
2. **Plan (≤5 steps):**
   1. `[code]` Select candidate pairs: main-cluster pairs first, then pairs where one paper cites the other, then by cosine, within per-paper and per-cluster caps.
   2. `[LLM]` For each pair, choose a relation and write `reason_short`, `reason_long`, evidence notes and span references from both papers, or abstain.
   3. `[code]` Copy the verbatim quotes from the selected spans; reject a citation claim the reference lists contradict.
   4. `[LLM]` Independent critic: supported, generic or insufficient; a generic reason is rewritten once with the critic's feedback.
   5. `[code]` Orient the edge (source → target), add citation notes, write edges to the world model; the `[LLM]` grading agent scores the stage.
3. **Tools:** `complete_json` (producer and critic, separate Nightshift scopes) → payload → validated decisions → one repair, then `LLMError`; OpenAlex reference lists already stored on each paper.
4. **Memory kept:** accepted edges and their dependencies → world model and map version; every decision (accepted, abstained, rejected, rewritten) → analysis audit; completed tasks → task cache.
5. **Rubric (0–3 × 3):** accuracy (every clause supported by both quotes), appropriateness (a specific, non-generic relation), actionability (the reason tells a reader why to read both papers); see `prompts/grader.md`.
6. **Stop conditions:** generic after one rewrite → drop; grade < 7/9 → redo once with the fix → continue with a warning. Abstaining is a valid result.
7. **Run log:** selected pairs and why, critic verdicts, rewrites; progress events `start`, `partial_result` (accepted edges) and `done`.
8. **Guardrails:** caps on pairs (4 within, 4 between, 2 per paper); bounded repair; a quote from one paper never supports a claim about the other; time limit and token budget checked before every call.

1. Reuse the Clusterer's original similarity matrix and original source fields.
2. Exclude title-only/insufficient-text records and detected duplicate studies (DOI/title).
3. Select bounded within-cluster and between-cluster paper pairs (code), main-cluster pairs first, then
   pairs where one paper cites the other (OpenAlex reference lists; these are candidates even below the
   similarity floor), then by cosine. Defaults: at most four within, four between, two per paper, two per
   side group, and one selected comparison per pair of different groups. This is not exhaustive.
4. Ask Nemotron (LLM) for one relationship or an explicit abstention. Relations: builds on / extends,
   same method in a different domain, same problem with a different method, benchmarks or compares
   against, directly cites. Contradiction is not a relation. Dates/similarity cannot prove influence.
   A `directly_cites` claim that contradicts known reference lists is rejected by code.
5. Require source-span references from BOTH target papers. Code resolves exact original
   quotes and bounds repair attempts. A neighbor's quote cannot support a target paper.
6. Independently verify proposed claims against original excerpts, without producer
   reasoning, scores or verdicts (LLM critic). Fresh Nightshift scopes isolate every call. A reason
   the critic marks `generic` ("both are about machine learning") is regenerated once with the
   critic's feedback; if it is still generic, the edge is dropped. The rewrite is in the trace.
7. Independently grade accepted findings, retain warnings and write typed findings to
   the World Model. A failed grade never obliges the producer to invent a connection.

Completed model tasks, including abstentions, are cached by complete inputs, full model
batch, source contexts, membership, model, prompts and schemas. Dependencies record the
referenced clusters and paper assignments.

**Edge object (spec D2).** Edges link two papers, never clusters. `paper_ids` is `[source, target]`: for
the directional relations the target builds on, benchmarks against or cites the source. Each edge has
`relation`, `similarity`, `reason_short` (one readable sentence; `description` keeps the same text for
older readers), `reason_long` (2-4 sentences), `evidence_notes` (short facts such as "shared method:
contrastive loss"; a citation note is added by code from the reference lists) and `evidence` (one
verbatim quote per paper), plus `verification="source_supported"`. On the map, hovering an edge shows
`reason_short`; clicking shows `reason_long`, the evidence and the similarity, in that order.
Sample mode adds an edge for every citation among the sample papers and one placeholder edge per cluster. This verification is a model
judgment, not an expert or formal entailment proof.

Use [the cached map analysis API](../grounded-findings.md) or the normal `/run` pipeline.
Numeric controls live in `Settings`. Citations come only from OpenAlex reference lists; papers from
other sources have none, so a citation between them is claimed only when a quote shows it.
