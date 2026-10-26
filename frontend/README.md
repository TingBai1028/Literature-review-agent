# Literature Map

React + TypeScript + Vite workspace for saved `/cluster` question maps. The graph renders
the actual paper memberships, scientific connections and provisional gap hypotheses.
It includes original source quotes, alternative-cluster scores, explicit move previews,
immutable versions, rollback, and version-bound human review.

## Run locally

From the repository root (Node 22.12+ and Python dependencies are required):

```bash
cd frontend
npm ci
npm run build
cd ..
python run.py
```

Open <http://127.0.0.1:8000/>. Build before starting the API: it mounts `frontend/dist`
at startup. Docker builds the frontend in a separate Node stage and serves it from the
same Python application. API routes take precedence over static files.

For development, keep the API running and use `npm run dev` in this directory.
Vite proxies `/api` to `http://127.0.0.1:8000` (override with `LITAGENT_API_PROXY`).

Opening the UI reads saved data and does not start a model call. **Search papers**, **New map**, **Run analysis**,
and applying a move in real mode can call the configured Nightshift model. The UI
shows the server's sample/real mode and the operation progress. Sample mode explicitly
labels its synthetic similarities, groupings and findings.

## Use the map

1. Choose a saved version, or **New map**. Two sources are available:
   - **Search online** (default): type a research question (years, citation counts or paper type
     can be stated in it) and a mode: **Fast** (retrieve ~300, show the best 50) or **Pro**
     (~1,000, show 50, read full text). `POST /search` runs the Planner and retrieval, ranks
     every paper by relevance and citations, stores the papers through Zetaris and returns the
     plan, a summary, the paper list (Human review 1) and the ranked backup pool. Nothing is approved automatically: untick papers to drop,
     or write feedback and **Search again with feedback** to re-plan (stated criteria are kept), then
     **Build the map from N kept papers** sends only the kept papers to `POST /cluster`.
   - **Import records**: import a JSON paper array, a `/cluster` request (`input.query`,
     `input.effort`, `input.papers`), or a response with `output.papers`. A supplied
     query/effort replaces the dialog's prefilled values. Try
     `input_examples/cluster-map/lora-translation.json`; it contains original records.
2. Click a topic or paper. Inspect its source evidence, full abstract, keywords and
   numerical alternatives. Every map has one main cluster (the most topic-related, centred and
   outlined), foundation clusters (classic work) and side clusters; each says why it got its role.
   Paper membership is exclusive. The layout is force-directed: similar papers sit closer, node
   size grows with citations and darker nodes are more recent. Positions are seeded and
   remembered per map lineage, so Graph 1, Graph 2 and refreshed versions keep papers in place. On a phone,
   topic navigation and the inspector show full labels; the overview omits dense labels.
   Drag the map with a finger and use the zoom controls to inspect individual nodes.
3. **Run analysis** shows Graph 1 (paper-to-paper edges) as soon as it is ready, then adds Graph 2
   (research gaps) on the same positions. Hover an edge for its one-line reason; click it for the
   longer reason, evidence and similarity. Edges always join two papers. Empty gap output is valid
   and does not prove no gap exists. **Swap papers** swaps the side papers for the next-best papers
   of the backup pool; main and foundation stay.
4. Select an eligible side-cluster target, **Preview move**, then explicitly apply the preview.
   Main and foundation papers stay fixed. The server validates the final simultaneous membership.
5. **Versions** lets you inspect old versions or explicitly set a completed version as current.
   A stale preview shows a conflict inside the dialog; it cannot overwrite a changed head.
6. While a run is in progress the map builds itself and an activity feed names the agent at work.
   Selecting any paper, cluster, edge or gap shows which agent created it and why; **Reasoning** lists
   every agent's steps (code or LLM, with setbacks highlighted). See [progress events](../docs/events.md).
7. **Human review** hides model decisions by default. Fill in the reviewer, reason, judgment
   and exact quotes from both original sources, then save. Reviewer identity is self-declared.
   Reading a review queue never creates human labels. Each version has its own annotations.
8. **AI grading** asks the independent Review Agent to grade the version's explicit claims
   on source support, question relevance and testability (0–3 each). **Show existing grades** only
   reads a cached report. Missing hypotheses receive no score. Suggestions and their original
   quotes appear separately from the human form; judgments are saved only by explicit submission.
   Identical Agent requests reuse the report. See [rubric and API](../docs/agents/review_agent.md).

The footer exposes failed grades, partial runs and warnings. Original full text is loaded
on demand only when supplied. High/Ultra searches fetch open-access PDFs into the records; maps
imported from JSON use whatever full text the records already contain.

## Verification

```bash
npm run build
npx playwright install chromium       # once, if no local Chrome is available
npm run test:e2e
# Alternative using an installed Chrome:
PLAYWRIGHT_CHANNEL=chrome npm run test:e2e
```

Tests launch temporary sample-mode APIs and fresh browser profiles. They exercise real
HTTP routes for analysis, evidence inspection, moves, rollback, explicit review saving,
JSON import, stale-version conflicts and mobile navigation. They never label the real
review pack or call a paid model. Screenshots/logs go to the OS temporary directory
(`LITAGENT_QA_OUTPUT` can override it), outside the repository.

The interface uses Chinese navigation with original paper titles and quotes preserved.
White surfaces, a cool pale sidebar, forest-green controls and native SVG nodes keep the
scientific records readable without decorative imagery or fabricated graph edges.
