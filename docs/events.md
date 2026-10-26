# Progress events

One stream carries both the live progress for the map (spec A1) and each agent's run log (spec B3).
It is the run's trace file, `logs/trace-<run_id>.jsonl`, served as server-sent events.

## Subscribing

The client chooses the run ID, subscribes, then starts the run with that ID:

1. `GET /runs/{run_id}/events` (`text/event-stream`), optionally `?after=<seq>` to resume.
2. `POST /search`, `POST /cluster` or `POST /run` with `"run_id": "<run_id>"`, or
   `POST /cluster/{source}/analyze` with `"run_id": "<new version id>"`.

Events already written are replayed first, then new ones follow as each step logs. The stream ends after
the run's terminal event. If the run never starts it ends with an `error` event after
`event_stream_wait_s` (60 s), and at the latest `event_stream_grace_s` (300 s) after the run's time limit.

## Event shape

Each event is one `data:` line holding JSON:

```json
{
  "run_id": "r_123",
  "seq": 42,
  "ts": "2026-10-26T08:00:00+00:00",
  "agent": "clusterer",
  "phase": "partial_result",
  "message": "Clusterer: grouped 30 papers into 4 clusters; naming them next",
  "payload": {"clusters": [{"id": "MAIN", "kind": "main", "paper_ids": ["W1", "W9"]}]},
  "step": "group papers",
  "step_kind": "code",
  "decision": "4 clusters",
  "result": null,
  "next": "",
  "why": "",
  "terminal": false
}
```

- `phase`: `start` (an agent begins), `step` (any logged decision), `partial_result` (something the map
  can draw now), `done` (an agent finished), `error`.
- `step_kind`: `code` (deterministic), `llm` (a model call) or `human` (spec B2).
- `step`, `decision`, `result`, `next`, `why`: the run log fields (spec B3).
- `message`: one plain sentence for the activity feed.
- `payload`: present on partial results and agent ends; kept whole, unlike `result`, which is shortened.

## Partial results

| Agent | When | `payload` |
| --- | --- | --- |
| retriever | after each search | `papers_fetched`, `target`, `paper_ids` of that search |
| retriever | done | `paper_ids` kept |
| clusterer | roles assigned | `clusters`: `id`, `kind`, `paper_ids` (labels follow) |
| clusterer | clusters named | `clusters`: plus `label`, `role_reason` |
| connection_finder | each batch of accepted edges | `edges`: `id`, `source`, `target`, `relation`, `reason_short` |
| gap_finder | each cluster's gaps | `gaps`: `id`, `cluster_id`, `paper_ids`, `description`, `label` |

Groups of pairs and clusters run at the same time (`LLM_CONCURRENCY`), so these events arrive in the order
the model answers, not in cluster order. Each carries its own `cluster_id`s; the final result is in cluster order.

## In the map UI

- **Live map (spec A2, A4).** Building a map: papers appear, glide into their clusters as soon as they are
  grouped (the grouped event carries the same nearest-neighbour pairs as the saved map, so nothing jumps when the
  run finishes), then the clusters get their names. Analysis: edges draw in as each batch is accepted (Graph 1),
  then gap markers appear (Graph 2). The map can be panned, zoomed and clicked throughout.
- **Activity feed (A3).** While a run is in progress a panel shows each start, partial result, end and setback
  as a plain sentence, newest at the bottom, and names the agent at work. The search dialog shows the
  retriever's running count ("已获取 N / 300 篇").
- **Reasoning panel (B4, B5).** The 推理过程 tab lists every agent's steps for the open version and its whole
  lineage (map, Graph 1, Graph 2, refreshes, moves), read from `GET /runs/{run_id}/log`. Each step is marked
  代码 or LLM; critiques, retries, fallbacks and errors are highlighted; raw data is behind 详情.
- **Provenance (B6).** Selecting a paper, cluster, edge or gap shows which agent created it and why.
