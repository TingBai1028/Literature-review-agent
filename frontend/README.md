# Literature Map

React + TypeScript + Vite workspace for saved `/cluster` question maps. The graph renders
the actual paper memberships, scientific connections and provisional gap hypotheses.
It includes original source quotes, alternative-cluster scores, explicit move previews,
immutable versions, rollback, and a floating graph-feedback assistant.

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

Opening the UI and searching the header read saved data without model calls. Thumbs-up only saves approval.
Online paper retrieval, creating a map, continuing analysis, applying a move, thumbs-down and submitting
assistant feedback in real mode can call the configured Nightshift model. The UI
shows the server's sample/real mode and the operation progress. Sample mode explicitly
labels its synthetic similarities, groupings and findings.

## Use the map

1. Choose a saved version, or **Create new map** (top bar) for another research question. Two sources are available:
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
   During retrieval, **Cancel**, the dialog close button and Escape remain available. They abort the request
   and close the dialog; late results are ignored. The backend stops between provider requests, retries,
   embedding batches and later stages. An already-issued provider request may finish first.
2. The topic list shows every cluster and scrolls within the available sidebar height, with no fixed topic limit.
   Taller screens naturally show more topics. Click a topic or paper. Inspect its source evidence, full abstract, keywords and
   numerical alternatives. Every map has one main cluster (the most topic-related, centred and
   outlined), foundation clusters (classic work) and side clusters; each says why it got its role.
   Paper membership is exclusive. The layout is force-directed: similar papers sit closer, node
   size grows with citations and darker nodes are more recent. Positions are seeded and
   remembered per map lineage, so Connection graph, Gap graph and refreshed versions keep papers in place. On a phone,
   topic navigation and the inspector show full labels; the overview omits dense labels.
   Drag the map with a finger and use the zoom controls to inspect individual nodes.
3. A new map continues on its own: Connection graph (paper-to-paper edges) appears as soon as it is ready,
   then Gap graph is added on the same positions. A **Continue analysis** action appears
   beside the map only when analysis is missing or unfinished; completed maps need no extra step.
   Hover an edge for its one-line reason; click it
   for the longer reason, evidence and similarity. Edges always join two papers. Empty gap output is
   valid and does not prove no gap exists. **Swap papers** (map toolbar, with the backup pool's size)
   swaps the side papers for the next-best papers of the backup pool; main and foundation stay.
   The icon beside the zoom buttons shows the whole map again (default zoom and position, all elements).
4. Select an eligible side-cluster target, **Preview move**, then explicitly apply the preview.
   Main and foundation papers stay fixed. The server validates the final simultaneous membership.
5. **Versions** lets you inspect old versions or explicitly set a completed version as current.
   A stale preview shows a conflict inside the dialog; it cannot overwrite a changed head.
6. While a run is in progress the map builds itself. A compact progress strip above the workspace names the
   agent at work; expand **Steps** to read recent events without covering paper details. **Reasoning** and graph feedback stay disabled until processing finishes, with a visible explanation, while papers remain readable.
   Selecting any paper, cluster, edge or gap shows which agent created it and why. Explanations are grouped by
   agent, with topic/similarity details separated from the reason. Paragraphs, headings, bullets, emphasis and
   inline code are rendered as readable text; paper references retain their full-title tooltips. **Reasoning** lists
   every agent's steps (code or LLM, with setbacks highlighted). See [progress events](../docs/events.md).
7. Search paper titles and topic names from the header with keywords, in any order. Results appear directly below the search box as you type,
   with a close button, Escape support and click-outside dismissal. There is only one search input. Paper results include their cluster; topic results open
   the cluster in the right panel. Search does not hide the map or the topic list.
8. Cluster, connection and gap details have thumbs-up/down icons. **Thumbs-up** saves approval without
   running a model. **Thumbs-down immediately regenerates the graph**, carrying that selected item into the feedback.
9. After Gap graph finishes, the **Graph feedback** assistant opens at the bottom right. Drag its header (or use
   arrow keys when focused), close it, or reopen the Feedback launcher. Type a change and choose **Update graph**.
   The backend revises clusters against original-source spans, then rebuilds and checks connections and gaps.
   Completed updates become a new active version and prompt for further feedback. A paused update leaves the current
   graph open and shows saved steps, the cause and **Resume update** / **Keep current graph** directly in the bot.
   Resume reuses the saved topics and retries only unfinished steps; service configuration or credit issues need
   resolving first. **Preview revised topics** is optional. Failed requests retain the typed feedback. In sample mode this is explicitly a demo revision:
   the conversation is saved but no model changes cluster membership.

The research-question strip is compact, with no paper/role counts; the bottom bar is removed. Move previews
are available beside the target selector in paper details. Original full text loads on demand when supplied.
High/Ultra searches fetch open-access PDFs; imported maps use the text supplied in the records.

## Verification

```bash
npm run build
npx playwright install chromium       # once, if no local Chrome is available
npm run test:e2e
# Alternative using an installed Chrome:
PLAYWRIGHT_CHANNEL=chrome npm run test:e2e
```

Tests launch temporary sample-mode APIs and fresh browser profiles. They exercise real
HTTP routes for analysis, evidence inspection, moves, rollback, keyword-search results, feedback revisions,
stale-version conflicts and mobile navigation. They never label the real
review pack or call a paid model. Screenshots/logs go to the OS temporary directory
(`LITAGENT_QA_OUTPUT` can override it), outside the repository.

The interface uses Chinese navigation with original paper titles and quotes preserved.
White surfaces, a cool pale sidebar, forest-green controls and native SVG nodes keep the
scientific records readable without decorative imagery or fabricated graph edges.
