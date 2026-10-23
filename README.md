# TODO: Project name

> TODO: One-sentence pitch. Example: *An agent that maps a research field for you: it finds the papers, groups them into ideas, shows how they connect, and points out where the gaps are, with every claim traced back to a source.*

**Open Agent Hackathon 2026 · Track 02 — The Agent That Can Explain Why**

| | |
| --- | --- |
| Demo video (1–4 min) | TODO: link |
| Slide deck | TODO: link |
| Live demo (optional) | TODO: link |

## The problem

TODO: 2–3 sentences. Who is the user (a research student starting a literature review?), what do they do today, and why is it slow or error-prone?

## What it does

TODO: Describe the flow from the user's side in 4–6 bullets.

- The user types a research question into a chat box and picks an effort level (Normal / Medium / High / Ultra).
- TODO
- TODO

## Architecture

The full diagram and design decisions are in [ARCHITECTURE.md](ARCHITECTURE.md).

Five agents run in sequence, each followed by a check:

| Step | Agent | Checked by |
| --- | --- | --- |
| 1 | Planner: turns the question into a search plan | Asks the user for a topic if none is given |
| 2 | Retriever: finds papers through scholarly APIs | Human review 1 |
| 3 | Clusterer: groups papers into labelled ideas | Grading agent |
| 4 | Connection finder: links papers within and between clusters | Grading agent |
| 5 | Gap finder: finds research gaps inside clusters | Grading agent, then Human review 2 |

Per-agent specs are in [docs/agents/](docs/agents/).

## Sponsor technology

See [docs/sponsor-tech.md](docs/sponsor-tech.md) for the full write-up.

| Sponsor | How we use it | Status |
| --- | --- | --- |
| Meterless Nightshift | Primary AI provider: every LLM call goes through it (`litagent/integrations/llm.py`, OpenAI-compatible client) | Wired; model ID still TODO |
| NVIDIA | Nemotron model, connected through Nightshift (the NVIDIA key lives in Nightshift's Providers tab). The trace logs the model that handled each request. | Model ID still TODO |
| Zetaris | Shared paper data layer, running locally in Docker (`litagent/integrations/zetaris.py`) | REST client wired; paper table TODO |
| Meterless World Model | Shared findings graph (clusters, connections, gaps), returned as `paper_map` for the paper map (`litagent/integrations/meterless.py`) | Interface + test ready; real engine not yet connected |
| Cursor (with SpaceX XAI) | Optional: development environment, project rules in `.cursor/rules/` | Optional |

Each sponsor integration sits behind its own adapter class, so an outage in one doesn't break the whole project, and sample mode runs without any of them.

## Getting started

### Requirements

- Python 3.11+
- For real runs: Meterless Nightshift with a Nemotron model, and Zetaris running locally in Docker (see `.env.example`). Sample mode needs neither.
- No GPU needed.

### Setup

```bash
git clone TODO-repo-url
cd TODO-repo-folder
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # then fill in your values
```

Set the Nemotron model ID in `litagent/config.py` (`NIGHTSHIFT_MODEL`).

### Run the API (main entry point)

```bash
SAMPLE_MODE=true python run.py   # serves POST /run on 0.0.0.0:$PORT (default 8000)
```

```bash
curl -X POST localhost:8000/run -H 'Content-Type: application/json' \
  -d '{"input": {"query": "How do large language models handle low-resource languages?", "effort": "normal"}}'
```

Request: `{"run_id": optional, "input": {"query": str, "effort": "normal|medium|high|ultra", "feedback": optional str}}`

- Success: `{"run_id": ..., "status": "success", "output": {plan, papers, clusters, connections, gaps, paper_map, warnings, ...}}`
- Failure: `{"run_id": ..., "status": "error", "error": {"type": ..., "message": ...}}` (HTTP 422 for bad input, 500 for a failed stage)
- No topic in the query: `status: "success"` with `output.status: "need_topic"` and a friendly `message_to_user`.
- Human reviews never wait for input through `/run`. Both are approved unless you pass `feedback`, which sends that comment back to the Planner once (Human review 1).
- `output.status: "partial"` means the run hit `RUN_TIMEOUT_S` (default 600 s) and returned what it had finished.

### Sample mode

`SAMPLE_MODE=true` runs the whole pipeline with no Zetaris, Nightshift or network access. Papers are real OpenAlex records saved in `data/sample/`; clustering, connections, gaps and grades are placeholders labelled "Sample mode".

### Examples

`input_examples/` holds 4 `/run` requests (normal, medium with feedback, high, and no topic). `output_examples/` holds the matching responses, generated in sample mode:

```bash
SAMPLE_MODE=true python run.py &
for f in input_examples/*.json; do
  curl -s -X POST localhost:8000/run -H 'Content-Type: application/json' -d @$f | python -m json.tool --indent 2 > output_examples/$(basename $f)
done
```

`pytest` checks that each input still produces its output.

### Docker

```bash
docker build -t litagent .
docker run --rm -p 8000:8000 -e SAMPLE_MODE=true litagent
# Real run: Zetaris and Nightshift run on your machine, outside the container
docker run --rm -p 8000:8000 --env-file .env litagent
```

Inside the container, `localhost` is the container itself: point `ZETARIS_REST_URL` and `METERLESS_BASE_URL` at `host.docker.internal` instead (on Linux, add `--add-host=host.docker.internal:host-gateway`). Dependencies are installed at build time; nothing is downloaded at runtime.

### Command line

```bash
python -m litagent "How do large language models handle low-resource languages?" --effort normal --sample-mode
python -m litagent "TODO your question" --effort medium      # real run, human reviews asked in the terminal
```

### Logs

Every run writes `logs/trace-<run_id>.jsonl` (one JSON object per line) and prints readable `[INFO]` lines to stdout. Each event has `timestamp, run_id, agent_name, action, decision, result, next, why`. LLM calls add the model that handled the request and token usage. Zetaris queries, Meterless World Model writes, grades, redos, fallbacks and errors are all logged. Tokens and keys are masked.

### Run time

Every external call has a timeout (model requests 60 s, Zetaris SQL 45 s, OpenAlex 30 s), redos and replans are capped in `litagent/config.py`, and the run stops between stages after `RUN_TIMEOUT_S` (default 600 s). The target is 5–10 minutes; Ultra (~150 papers, full text) may hit the cap and return a partial result.

### Tests

```bash
pytest
```

## Evaluation

TODO: Summarise results from [docs/evaluation.md](docs/evaluation.md). Example: *"On N test topics with published survey papers, cluster agreement was X% and gap recall was Y%."*

## Data

- **Real runs:** paper metadata comes from open scholarly APIs (OpenAlex now; Semantic Scholar and arXiv planned) and is stored in Zetaris for the later agents.
- **Sample mode and tests:** `data/sample/` holds about 60 real OpenAlex papers for each of 3 topics (OpenAlex data is CC0). Recreate or add topics with `scripts/download_sample_data.py`.
- See [data/README.md](data/README.md) for sources and licences. No sensitive or restricted data is stored in this repo.

## Pre-existing components

See [docs/pre-existing-components.md](docs/pre-existing-components.md). Everything else was built during the hackathon (22–27 October 2026).

## Limitations and next steps

- TODO

## Team

| Name | Role |
| --- | --- |
| TODO | TODO |

## Licence

TODO: Choose a licence after checking the Official Rules (section 09, Intellectual property).
