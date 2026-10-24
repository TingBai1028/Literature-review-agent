# Front end

TODO: choose a stack (e.g. React + a graph library such as Cytoscape.js or react-force-graph, or Streamlit for speed).

## What it needs to show

1. **Chat box** for the research question, plus an effort selector (Normal / Medium / High / Ultra).
2. **Human review 1:** summary and paper list, with a box for feedback ("only papers after 2022", "more review papers").
3. **Paper map:** clusters, connections and gaps rendered from the Meterless world model (`output.paper_map` in the `/run` response: `nodes` with `id`/`type`/attributes, papers with `authors`; `edges` of type `member-of`, `connects-to` (with `evidence`) and `between`). `GET /world/{run_id}` returns the full world, including the author review queue.
   - Clicking a connection or gap shows its evidence: the paper and the quote.
4. **Human review 2:** thumbs up / down and a follow-up message box.
5. **Trace view (optional, good for the demo):** the steps from `logs/trace-<run_id>.jsonl`, including grading scores and redos.

## Connecting to the pipeline

`POST /run` (`litagent/api.py`, started by `python run.py`) runs the pipeline and returns JSON. It never waits for input: pass the user's Human review 1 comment as `input.feedback` to re-plan.
TODO: for fully interactive reviews, implement the `Reviewer` interface in `litagent/human_review.py` so they come from the UI.
