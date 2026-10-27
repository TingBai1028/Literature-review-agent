# Graph feedback

The map uses thumbs-up/down in cluster, connection and gap details, plus a draggable feedback assistant
that opens after graph generation. The separate Human review page has been removed. Earlier annotation
and per-finding AI-review APIs remain available for saved evaluations and API clients.

- Thumbs-up saves approval without calling a model.
- Thumbs-down immediately requests a graph revision, including the selected item as context.
- A typed message followed by **Update graph** requests a revision of the whole graph.

Revisions use the saved question, original papers and cached embedding/similarity arrays. They do not rerun
paper retrieval. The cluster agent may split, merge, rename or move papers, but each original paper must occur
exactly once and exactly one cluster must be main. Multi-paper clusters require original-source span references
from every member. Code resolves those references to verbatim quotes and rejects invented spans. Membership
hints and cluster cards are rebuilt, then connections, gaps, independent verification and grading run again with
the human's instructions. Feedback requests are not treated as scientific evidence.

Each completed update creates an immutable version and moves the active head. A failure before valid clusters
leaves the existing map active; a later interruption saves an unfinished version for recovery without replacing
the active version. Feedback instructions persist when finding analysis resumes. Votes belong to the version
reviewed; new findings start without approval. The conversation carries forward. The assistant retains an
unsent draft when an HTTP request fails. **Versions** provides access to earlier maps and rollback.

A paused update keeps the current graph open. The bot shows completed and pending steps, a plain-language
service/configuration/credit/timeout explanation, and direct **Resume update** and **Keep current graph** actions.
Resume uses the saved topics and findings instead of re-running completed work. The feedback conversation stays
attached to the update, including when resuming through the map's analysis action. Keeping the current graph
clears the recovery prompt while retaining the draft. A new feedback request is blocked until the paused update
is resumed or dismissed. Existing saved drafts from the earlier workflow are discovered when opening their
current graph; they do not require a data migration or model call. Fresh workspace visits open the current
version for the most recently used question, while an explicit version URL still opens that version.

## API

All routes use the existing `{status, output}` response envelope.

| Route | Purpose |
| --- | --- |
| `GET /cluster/{run_id}/feedback` | Read saved votes and conversation without running a model |
| `POST /cluster/{run_id}/feedback/vote` | Save `expected_version_token`, `target: {kind, id}` and `vote: up\|down` |
| `POST /cluster/{run_id}/feedback/dismiss` | Keep the current graph with `expected_version_token` and `expected_update_run_id`, preserving the saved draft |
| `POST /cluster/{run_id}/feedback/regenerate` | Submit `expected_version_token`, a 32-character hex `request_id`, `text`, optional `target` and optional new `run_id` |

Regeneration requires the active version and returns `{map, feedback}`. `feedback.update` records its outcome,
saved draft ID, current graph ID, completed/pending steps and a readable reason. A paused result returns the
current graph's feedback state, preserving its approvals. Resume posts to the existing
`POST /cluster/{draft_run_id}/analyze` with the draft's version token, a fresh request ID and both finding stages;
its result includes the preserved human instructions and its feedback record reflects the resumed outcome. Request receipts prevent a completed
request from calling agents twice; the same request ID with changed instructions is rejected. A root lock and
version-token checks prevent stale concurrent edits. A failed receipt requires a new request ID to retry.
Messages are limited to 4,000 characters; conversation display retains the most recent 50 messages. The source
excerpts use the existing finding-source limits. Run warnings remain visible in **Reasoning**.

Sample mode records feedback and creates a clearly labelled demo revision without model-driven changes to
cluster membership. It validates the interaction flow, not the semantic quality of a live revision.
