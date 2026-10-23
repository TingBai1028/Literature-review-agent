# Front end

TODO: choose a stack (e.g. React + a graph library such as Cytoscape.js or react-force-graph, or Streamlit for speed).

## What it needs to show

1. **Chat box** for the research question, plus an effort selector (Normal / Medium / High / Ultra).
2. **Human review 1:** summary and paper list, with a box for feedback ("only papers after 2022", "more review papers").
3. **Paper map:** clusters, connections and gaps rendered from the Meterless world model (`WorldModel.to_graph_json()`).
   - Clicking a connection or gap shows its evidence: the paper and the quote.
4. **Human review 2:** thumbs up / down and a follow-up message box.
5. **Trace view (optional, good for the demo):** the steps from `runs/<run_id>.jsonl`, including grading scores and redos.

## Connecting to the pipeline

TODO: expose `litagent.orchestrator.run_pipeline` through a small API (e.g. FastAPI), and implement the `Reviewer` interface in `litagent/human_review.py` so human reviews come from the UI instead of the terminal.
