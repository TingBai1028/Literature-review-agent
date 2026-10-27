# Literature Map

> Ask a research question and get a map of the literature: the papers that answer it, the work around it, how papers connect, and which questions are still open. Every grouping, connection and gap points to the exact sentence that supports it, and an independent check rejects what the sources don't support.

**Open Agent Hackathon 2026 · Track 02 — The Agent That Can Explain Why**

| | |
| --- | --- |
| Demo video (1–4 min) | https://docs.google.com/presentation/d/1wr8P2x30y1zl8GBFVFt-onIHQl7OJOrDFqfiHxkir0E/edit?usp=sharing |
| Slide deck | https://docs.google.com/presentation/d/1Y2rJS4OAAlqHpdCI4WA3lBMMNk28bcJq3oCIkmWOtxA/edit?usp=sharing |
| Repository | <https://github.com/TingBai1028/Literature-review-agent> |

## The problem

A research student starting a literature review searches a few databases, skims dozens of abstracts, and slowly builds a mental map: which papers answer the question, which only share its keywords, how they relate, and where nobody has looked yet. It takes days. AI assistants speed this up, but they tend to state plausible connections and "research gaps" that the papers never support, and the student can't tell which claims to trust.

Literature Map does the same mapping in minutes and shows its work. A claim is only kept if it quotes both papers it is about, word for word, and passes a separate check. When the sources don't support a finding, the agent abstains instead of guessing.

## What it does

1. **Ask.** Type a research question in plain words (years, citation counts or paper types can be part of it) and pick a mode:
   - **Fast**: retrieves about 300 papers and maps the 50 most relevant, from their metadata and abstracts.
   - **Pro**: retrieves about 1,000 papers, maps 50, and reads the full open-access text of the most relevant ones.
2. **Check the papers (Human review 1).** The Planner turns the question into a search plan, or asks for a topic if there isn't one. The Retriever searches OpenAlex and arXiv, removes duplicates and drops papers that aren't about the question. You keep or remove papers, or write feedback ("only since 2023") to search again.
3. **Get the map.** The map builds itself in three steps, each shown as soon as it is ready:
   - **Clusters.** One **main** cluster holds the papers most related to the question, a **foundation** cluster the older, highly cited work they build on, and **side** clusters the rest.
   - **Connection graph.** Pairs of papers that really relate, each with a short reason, a longer explanation and a quote from both papers.
   - **Gap graph.** Testable research hypotheses between papers, each checked against the literature with an OpenAlex search for a study that already answers it.
4. **Explore and judge (Human review 2).**
   - **Look:** click any paper, cluster, connection or gap to see its quotes and who made it and why. Paper IDs in agent-written text appear as the paper's title.
   - **Change the map:** move papers between side clusters (with a preview, versions and rollback), or swap side papers for the next-best ones from the backup pool.
   - **Find:** search paper titles and topics from the header. Results appear below the search box as you type, showing each paper with its cluster; selecting a result opens its details.
   - **Give feedback:** use thumbs-up to save approval or thumbs-down to immediately regenerate the graph. After the graph finishes, a draggable feedback assistant opens at the bottom right. Type a change and choose **Update graph** to revise clusters, connections and gaps from the original sources. Each update creates a new version; earlier versions remain available. See [graph feedback](docs/graph-feedback.md).

## How it explains itself

- **Verbatim evidence.** Models cite numbered source spans; code copies the quoted text, so a quote can't be invented. In the recorded evaluation, 218 of 218 quotes were verbatim from the paper they are attributed to.
- **Independent checks, by a second model family.** The agents that build the map run on Nemotron; every check of their work runs on DeepSeek, so the checker doesn't share the producer's blind spots. Every connection is re-checked by a separate call that sees only the claim and the sources, not the reasoning that produced it, and grading agents score each stage from 0 to 9 against the source papers.
- **Abstaining is allowed.** An empty result is a valid result. A gap whose literature search did not run is marked **novelty unverified** and listed after verified gaps.
- **Every step is visible.** The live activity feed and the **Reasoning** tab show each agent's steps, marked as code, LLM or human, with retries and fallbacks highlighted. "Who made this, and why" appears on every element of the map, and every run writes a full trace to `logs/trace-<run_id>.jsonl`.

## Architecture

Five agents run in sequence; each finding stage is checked before the next one starts. The full diagram and design decisions are in [ARCHITECTURE.md](ARCHITECTURE.md), and each agent's spec (goal, steps, tools, rubric, stop conditions, guardrails) is in [docs/agents/](docs/agents/).

| Step | Agent | Checked by |
| --- | --- | --- |
| 1 | [Planner](docs/agents/planner.md): turns the question into a search plan | Asks for a topic if none is given |
| 2 | [Retriever](docs/agents/retriever.md): searches scholarly APIs, ranks by relevance and citations, keeps a backup pool | Human review 1 |
| 3 | [Clusterer](docs/agents/clusterer.md): main, foundation and side clusters, each named with quoted evidence | [Grading agent](docs/agents/grading_agent.md) |
| 4 | [Connection finder](docs/agents/connection_finder.md): paper-to-paper edges with reasons (Connection graph) | Independent verifier, grading agent |
| 5 | [Gap finder](docs/agents/gap_finder.md): testable gaps between papers (Gap graph) | Coverage search, gap grader, grading agent, then Human review 2 |

Agents exchange typed Pydantic models (`litagent/schemas.py`), never free text. The floating feedback assistant replaces the separate Human review page. An independent [review agent](docs/agents/review_agent.md) remains available through the API for per-finding assessment.

## Sponsor technology

The full write-up, with evidence from real runs, is in [docs/sponsor-tech.md](docs/sponsor-tech.md).

| Sponsor | How we use it |
| --- | --- |
| **Meterless Nightshift** | Primary AI provider: every model call goes through it (`litagent/integrations/llm.py`, OpenAI-compatible client). Each run gets its own answer-cache partition, and each call its own answer-memory scope. |
| **NVIDIA** | Nemotron 3 Ultra (`nvidia/nemotron-3-ultra-550b-a55b`, `NIGHTSHIFT_MODEL` in `litagent/config.py`) through Nightshift's NVIDIA provider, for every agent that builds the map. The checks (grades, verifiers, AI review) run on DeepSeek V4 Pro 0813 through Nightshift's OpenRouter provider (`GRADER_MODEL`). The trace logs the model that answered each call. |
| **Zetaris** | Shared paper data layer, running locally in Docker. The Retriever writes papers to our paper store, which Zetaris serves as `litagent_db`; every later agent reads them back with Zetaris SQL (`litagent/integrations/zetaris.py`). |
| **Meterless World Model** | Implemented in Python from Meterless's spec and reference (`litagent/integrations/world_model/`), passing all 8 Meterless conformance checks. It holds each run's papers, authors, clusters, connections (with evidence) and gaps; `/run` returns it as `paper_map` and `GET /world/{run_id}` serves it. |
| **Cursor** | Development environment, with the project's architecture and conventions in `.cursor/rules/project.mdc`. |

Each sponsor integration sits behind its own adapter class, so an outage in one doesn't break the run, and sample mode runs without any of them.

## Getting started

### Requirements

- Python 3.11+, and Node 22.12+ to build the web interface.
- For real runs: Meterless Nightshift with NVIDIA and OpenRouter provider credentials, and Zetaris running locally in Docker ([docs/setup-zetaris.md](docs/setup-zetaris.md)). Sample mode needs none of these services or credentials.
- Recommended: a free OpenAlex API key (`OPENALEX_API_KEY`), which raises OpenAlex's limit from about 100 to about 1,000 searches a day. Set `OPENALEX_DAILY_SEARCH_LIMIT` to match.
- No GPU.

### Judge quick start: sample mode

Use this path first to check the interface and API. After installing Python and Node dependencies, sample mode needs no API keys, Docker, embedding-model download or running sponsor services. Installation itself requires internet access. Run these commands from a terminal using Bash or Zsh:

```bash
git clone https://github.com/TingBai1028/Literature-review-agent.git
cd Literature-review-agent
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cd frontend
npm ci
npm run build
cd ..
SAMPLE_MODE=true python run.py
```

On Windows PowerShell, use `py -3 -m venv .venv` and `.\.venv\Scripts\Activate.ps1`, then the same dependency/build commands; start with `$env:SAMPLE_MODE="true"; python run.py`. If `python3` is unavailable on another platform, use the command for your Python 3.11+ installation.

Open <http://127.0.0.1:8000/>. A fresh checkout has **no saved maps** because `logs/` is not distributed. Choose **Create new map**, enter **How do large language models handle low-resource languages?**, leave **Fast** selected and choose **Search papers**. Review the saved sample papers, then choose **Build the map from N kept papers**. Connections and gaps follow automatically. Select a connection or gap to inspect its source quotes and explanation. Sample findings and grades are explicitly placeholders; use the [recorded real evaluation](docs/evaluation.md) to assess real-run evidence.

Keep that terminal running. In a second terminal, check `curl http://127.0.0.1:8000/health`; expect `{"status":"ok"}`. If the root page returns 404, build the frontend and restart `run.py`. If port 8000 is occupied, use `PORT=8001 SAMPLE_MODE=true python run.py` and open port 8001. See [frontend/README.md](frontend/README.md) for the interface.

### Real runs: configure the integrations

After the quick start, stop the sample server with Ctrl+C. Activate the same virtual environment and work from the repo root:

```bash
cp .env.example .env                   # once; preserve your existing .env if you have one
```

Fill in `.env` and configure both Nightshift model routes:

| Setting / service | Required value |
| --- | --- |
| `SAMPLE_MODE` | `false`; also run `unset SAMPLE_MODE` if sample mode was exported in your shell (PowerShell: `Remove-Item Env:SAMPLE_MODE -ErrorAction SilentlyContinue`) |
| `METERLESS_BASE_URL` | Nightshift's running OpenAI-compatible runtime, normally `http://localhost:8088/v1` |
| `METERLESS_RUNTIME_TOKEN` | The runtime token copied from Nightshift, not an NVIDIA, OpenAI or DeepSeek key |
| Nightshift **NVIDIA** provider | Your NVIDIA API key; producer model `nvidia/nemotron-3-ultra-550b-a55b` |
| Nightshift **OpenRouter** provider | Your OpenRouter key with access/credit for checker model `openrouter/deepseek/deepseek-v4-pro-0813` |
| `ZETARIS_REST_URL`, `ZETARIS_ORG_ID`, `ZETARIS_API_KEY` | Your local Zetaris connection values from [the setup guide](docs/setup-zetaris.md) |
| `PAPERS_DB_*` | Paper-store values from `.env.example`; keep its password and both connection URLs consistent |

Provider keys stay in Nightshift. A DeepSeek key entered in Nightshift's **OpenAI** field does not configure this OpenRouter route. To use your own DeepSeek key for its billing, configure it in [OpenRouter's BYOK settings](https://openrouter.ai/settings/integrations); Nightshift still needs the OpenRouter key. The independent checker is required by the default setup. An optional `GRADER_MODEL=nvidia/nemotron-3-ultra-550b-a55b` uses the NVIDIA route for checks too, but then producer and checker use the same model family.

Provision the local CPU embedding model. It is needed by real retrieval and clustering; runtime does not download it:

```bash
python scripts/setup_embeddings.py     # downloads the pinned SemCSE encoder and runs a CPU smoke check
```

For the smaller MiniLM encoder, set `EMBEDDING_PROFILE=minilm` in `.env` and run `python scripts/setup_embeddings.py --profile minilm`. Provision and runtime must use the same profile. No GPU is required.

Install and start Zetaris using [docs/setup-zetaris.md](docs/setup-zetaris.md) first. That is a **separate Docker bundle**; this repo's Compose file only starts our Postgres paper store. Then run from this repo's root:

```bash
docker compose up -d --wait            # our paper store (Postgres, localhost:5433); waits for readiness
python scripts/setup_zetaris.py        # creates the table, registers it in Zetaris, checks a round trip
python scripts/check_nightshift.py     # real producer call: prints the responding model and token use
python scripts/check_nightshift.py --grader  # real checker call: verifies the separate provider route
```

The two Nightshift checks make real model requests and may consume provider credit. Both must succeed for the default real-run setup; a working producer does not prove the checker is configured. `openrouter_key_missing` means the OpenRouter key is missing in Nightshift. Authentication, credit or unavailable-model errors must be resolved in the corresponding provider before continuing.

### Run the real web app

```bash
python run.py                          # serves the already-built app and API on http://127.0.0.1:8000
```

Confirm the interface indicates real mode, then choose **Create new map**. Opening saved maps makes no model calls. Retrieval, map generation and graph updates use your configured services and model credits. Build the frontend before starting `run.py` if you skipped the quick start or changed frontend code.

### Run the API (`POST /run`)

`run.py` is the entry point required by the hackathon. `POST /run` runs the whole pipeline without waiting for any input:

```bash
SAMPLE_MODE=true python run.py
```

Keep the server running and send the request from a second terminal:

```bash
curl -X POST localhost:8000/run -H 'Content-Type: application/json' \
  -d '{"input": {"query": "How do large language models handle low-resource languages?", "effort": "fast"}}'
```

- **Request:** `{"run_id": optional, "input": {"query": str, "effort": "fast" | "pro", "feedback": optional str}}`. The older levels `normal`, `medium`, `high` and `ultra` (30, 60, 100 and 150 papers) are still accepted.
- **Success:** `{"run_id": ..., "status": "success", "output": {plan, papers, clusters, connections, gaps, paper_map, usage, warnings, ...}}`.
- **Failure:** `{"run_id": ..., "status": "error", "error": {"type": ..., "message": ...}}`, with HTTP 422 for bad input and 500 for a failed stage.
- **No topic:** `output.status` is `"need_topic"`, with a friendly `message_to_user`.
- **Nothing found:** `output.status` is `"no_results"`, naming the filters used and suggesting broader terms.
- **Partial:** `output.status` is `"partial"` when the run hits its time limit or token budget; it returns everything finished so far, with the reason in `warnings`.
- **Reviews:** human reviews never wait for input through `/run`. Both are approved, unless `feedback` is given, which sends that comment back to the Planner once.

The web app uses further endpoints (`/search`, `/cluster`, `/cluster/{id}/analyze`, `/cluster/{id}/refresh`, versions and regeneration, `/runs/{id}/events`); see [docs/grounded-findings.md](docs/grounded-findings.md) and [docs/cluster-regeneration.md](docs/cluster-regeneration.md).

### Sample mode

`SAMPLE_MODE=true` runs the whole pipeline with no Zetaris, Nightshift or network access. Papers are real OpenAlex records saved in `data/sample/`; clusters, connections, gaps and grades are placeholders labelled "Sample mode".

### Examples

`input_examples/` holds four `/run` requests (three topics at different efforts, one with feedback, and one without a topic). `output_examples/` holds the matching responses, generated in sample mode, and `pytest` checks that each input still produces its output:

```bash
python scripts/regenerate_examples.py  # in-process and in sample mode; never calls a server on port 8000
```

### Docker

```bash
docker build -t litagent .
docker run --rm -p 8000:8000 -e SAMPLE_MODE=true litagent
docker run --rm -p 8000:8000 --env-file .env.docker litagent  # real run; configure host URLs below first
```

The build requires internet access and downloads Python/Node dependencies and the embedding model, even for a sample-mode image. Dependencies, the built interface and the model are included at build time; nothing is downloaded at runtime. Start sample mode first and use the same **Create new map** steps above; no saved maps are bundled.

For a real container run, complete host-side integration setup first. Inside the container, `localhost` is the container itself: set `ZETARIS_REST_URL=http://host.docker.internal:8888/api/v1.0`, `METERLESS_BASE_URL=http://host.docker.internal:8088/v1` and `PAPERS_DB_URL=postgresql://litagent:litagent-local@host.docker.internal:5433/litagent` in a separate `.env.docker` (adjust the database password to yours). Copy the other values from your configured `.env`, keep `SAMPLE_MODE=false`, and run with `--env-file .env.docker`. On Linux also add `--add-host=host.docker.internal:host-gateway` and ensure the host services accept connections from the Docker network. Zetaris's own container must separately be able to reach `PAPERS_DB_JDBC_URL`.

### Command line

```bash
python -m litagent "How do large language models handle low-resource languages?" --effort fast --sample-mode
python -m litagent "How does LoRA fine-tuning improve low-resource machine translation?" --effort fast   # real run, reviews in the terminal
python scripts/try_search.py "your question" --effort fast --feedback "only review papers"         # Planner and Retriever only
```

## Reliability

- **Time.** Every external call has a timeout: model requests 90 s, Zetaris SQL 45 s, OpenAlex 30 s, PDFs 20 s. Each request (a search, a map, an analysis stage) stops between steps after `RUN_TIMEOUT_S` (600 s) and returns what it finished.
- **Tokens.** Each mode has a token budget, retries included: Fast 350k and Pro 800k (`EFFORT_PROFILES` in `litagent/config.py`, set from measured runs). The run stops between calls once the budget is exhausted; a response can overshoot because its usage is reported afterward.
- **Slow or failed model calls cost as little as possible.**
  - **Timeouts:** a timed-out request isn't sent again unchanged. A batch is asked again in two smaller halves; a single item falls back.
  - **Unnamed clusters:** a cluster whose name couldn't be generated is named again once at the end, if time allows.
  - **Missing grades:** a missing grade stays pending and is retried by the next analysis.
  - **Invalid or echoed answers:** an answer that fails validation is repaired once; an answer that only repeats the request is sent again.
- **Parallel calls.** Independent model calls run at the same time (`LLM_CONCURRENCY`, default 4): relevance and naming batches, connection groups and each cluster's gaps. Results and their order are the same as one after another.
- **Bounded finding grades.** Stage grading sends at most 5 findings or abstained pairs and 48,000 JSON payload characters per request, with only the relevant sources and deduplicated original quotes. Every item is checked; the lowest-scoring batch sets the stage grade. A failed batch leaves the grade pending. [Sizing evidence](docs/benchmarks/grading-payload-size.json) is an offline check, not a live latency benchmark.
- **Search budget.** OpenAlex results are cached for 24 hours. A shared daily request cap stops requests once the day's limit is used, and gap coverage searches have their own per-run budget ([docs/search-budget.md](docs/search-budget.md)).

## Logs

Every run writes `logs/trace-<run_id>.jsonl`, one JSON event per line with `timestamp, run_id, agent_name, action, decision, result, next, why`. Model calls add the model that answered, token usage, Nightshift cache status and timeouts with their duration. Zetaris queries, World Model writes, grades, redos, fallbacks and errors are all logged, and keys and tokens are masked. The World Model of each run is saved to `logs/world-<run_id>.json` (`GET /world/{run_id}`), and the web app streams the same events from `GET /runs/{run_id}/events`.

## Tests

```bash
python -m pytest -q                                              # 517 passed (27 Oct); no real model calls
cd frontend && PLAYWRIGHT_CHANNEL=chrome npx playwright test     # browser tests on a sample map
```

Scripts in `scripts/` check single stages on real data: `check_clusters.py`, `check_question_map.py`, `check_findings.py`, `check_cluster_regeneration.py` and `benchmark_similarity.py` (see [docs/agents/clusterer.md](docs/agents/clusterer.md)).

## Evaluation

**Latest recorded recovery, 27 October: a real 50-paper map produced 7 connections and 31 candidate research gaps.** Both finding stages completed and the missing grade was recovered without rerunning retrieval, clustering or the finders. The saved result passed 17/17 recovery checks, including exact source quotes and unchanged snapshots ([recovery report](docs/benchmarks/grade-recovery.json)).

These are **candidate hypotheses**, not established novel discoveries: 16 coverage checks found no addressing study in the checked sources; 15 searches were unavailable. The two recovery requests took 312.3 s and 159.9 s and used 412,398 and 13,784 tokens respectively. These are recovery costs, not a fresh end-to-end runtime. The first response exceeded its 350k-token budget and was preserved as a partial result; the follow-up only restored the missing grade. See the [evaluation details](docs/evaluation.md) for the evidence and limitations.

The earlier fixed-topic evaluation used three real runs at the older Normal level (30 papers each: LLMs for low-resource languages, GNNs in drug discovery, transformers for protein structure) on 26 October 2026 ([raw data](evals/results.json)):

- **218 / 218 evidence quotes are verbatim** from the paper they are attributed to.
- 22 connections were kept, each with quotes from both papers. This older evaluation kept zero gaps: in its completed run, 4 of 6 candidates abstained and 2 verified hypotheses were removed because a paper in the corpus already answers them. The later 31-gap recovery above is a separate run.
- 1 run completed (538 s, 231k tokens); 2 ended `partial` after Nightshift latency spikes timed out the connection stage. Those runs kept their finished stages, and timeouts are handled as described under Reliability.

Cluster agreement and gap recall against published surveys, and blind human judgements, need answer keys and reviewers; no model output is counted as either ([docs/evaluation.md](docs/evaluation.md)).

## Data

- **Real runs:** paper metadata from open scholarly APIs (OpenAlex and arXiv; Semantic Scholar when `SEMANTIC_SCHOLAR_API_KEY` is set), stored through Zetaris for the later agents. Pro adds the text of open-access PDFs.
- **Sample mode and tests:** `data/sample/` holds about 60 real OpenAlex papers for each of 3 topics (OpenAlex data is CC0). Add topics with `scripts/download_sample_data.py`.
- No sensitive or restricted data is stored in this repository. Sources and licences: [data/README.md](data/README.md).

## Pre-existing components

Declared in [docs/pre-existing-components.md](docs/pre-existing-components.md): the Meterless World Model spec and reference, Zetaris's getting-started guides, two pretrained embedding models, the SGHA gap-labelling prompt and the Source Serif 4 typeface. Everything else was built during the hackathon (22–27 October 2026).

## Limitations and next steps

- **Quality is not expert-validated yet.** Grades and verifications are model judgements: DeepSeek checks Nemotron's work, which makes them independent of the producer but not of model judgement in general. The blind cluster-pair review and the per-finding human reviews are ready but still need human reviewers, and survey answer keys for cluster agreement and gap recall aren't filled in.
- **Findings are deliberately sparse.** A finding needs quotes from both papers and an independent check, so narrow or abstract-only corpora can yield few connections and gaps. That is intended, but a strong gap needs a richer corpus or full text.
- **Full text means open-access PDF text, not deep reading.** Pro extracts the text of open-access PDFs and quotes the passages closest to the question. The Meterless Markovian engine for whole-paper reasoning is not connected (`meterless.read_in_chunks` is the adapter point).
- **Searches are bounded.** Candidate pairs, coverage searches and results per query are capped for cost, so "no study found" never means a gap is new to the world. Papers behind paywalls are never downloaded, so institutional access is not supported.
- **Cost and time.** A real 50-paper Fast map with both graphs takes several minutes and a few hundred thousand tokens, mostly source-grounded relevance checks and grading.
- **Next:** whole-paper reasoning with the Markovian engine, citation-graph signals, human-validated evaluation sets, and joining a user's own library through Zetaris.

## Team

Ting Bai and Xin Tian built the project together and worked across all of it. Their main areas, from the git history:

| Name | Main areas |
| --- | --- |
| Ting Bai | Project setup and hackathon requirements, Nightshift and Nemotron integration, Planner, Retriever, Zetaris paper store, Meterless World Model, reliability fixes and the English interface |
| Xin Tian | Question-aware clustering and cluster roles, Connection and Gap finders, review agent, interactive map, Fast/Pro modes, evaluation, parallel model calls and search budgets |

## Licence

Apache License 2.0; see [LICENSE](LICENSE). The ported Meterless World Model keeps its own Apache-2.0 notice in `litagent/integrations/world_model/LICENSE-meterless-world-model`.
