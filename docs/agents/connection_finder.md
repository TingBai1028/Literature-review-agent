# 4. Connection finder agent

Code: `litagent/agents/connection_finder.py`, `litagent/finding_engine.py`.
Prompts: `prompts/connection_finder.md`, `prompts/connections_verify.md`.

**Status:** Real source-grounded implementation plus offline sample branch.

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
