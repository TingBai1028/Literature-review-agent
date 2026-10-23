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

| Sponsor | How we use it |
| --- | --- |
| Zetaris | TODO: shared data layer that serves paper data to every agent |
| Meterless | TODO: world model (shared findings graph) and Markovian engine (chunked full-text reading) |
| Cursor (with SpaceX XAI) | TODO: development environment |
| NVIDIA | TODO: compute, if used |

## Getting started

### Requirements

- Python 3.11+
- TODO: Zetaris and Meterless access (see `.env.example`)

### Setup

```bash
git clone TODO-repo-url
cd TODO-repo-folder
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # then fill in your keys
```

### Run

```bash
# End-to-end run with fake data, no keys needed (good for checking the pipeline)
python -m litagent "How do large language models handle low-resource languages?" --effort normal --dry-run

# Real run, with human review prompts in the terminal
python -m litagent "TODO your question" --effort medium
```

Every run writes a step-by-step trace to `runs/<run_id>.jsonl`.

### Tests

```bash
pytest
```

## Evaluation

TODO: Summarise results from [docs/evaluation.md](docs/evaluation.md). Example: *"On N test topics with published survey papers, cluster agreement was X% and gap recall was Y%."*

## Data

Paper metadata comes from open scholarly APIs. See [data/README.md](data/README.md) for sources and licences. No sensitive or restricted data is stored in this repo.

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
