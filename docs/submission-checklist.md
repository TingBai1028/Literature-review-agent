# Submission checklist

**Deadline: 27 October 2026, 23:45 UTC** (= 28 October, 10:45 am Sydney time). Submit on HackOS. The team locks at first submission.

Source: participant onboarding deck. Final requirements are in the Official Rules on the event page; check them before submitting.

## Required items

- [ ] **Demo video**: 1–4 minutes, agent in action; open Graph 2 and show at least one real gap with both original source quotes and its coverage status; link goes in the README and `metadata.json`
- [ ] **Slide deck**: problem, user, solution, architecture (link goes in the README and `metadata.json`)
- [x] **GitHub repository**: public at <https://github.com/TingBai1028/Literature-review-agent>, README with run instructions
- [x] **Sponsor tech explanation**: Meterless (Nightshift + World Model), Zetaris, NVIDIA, Cursor → `docs/sponsor-tech.md`
- [x] **Pre-existing components** declared → `docs/pre-existing-components.md`
- [x] **Project details**: Literature Map, description, Ting Bai and Xin Tian, Track 02 → `metadata.json`

## Technical execution requirements

- [x] Public GitHub repo
- [x] `run.py` at the repo root; `POST /run` returns `success` / `error` JSON (never crashes silently)
- [x] At least 3 examples: `input_examples/` + matching `output_examples/` (4 pairs, sample mode; `pytest` checks them)
- [x] `SAMPLE_MODE=true` runs end to end with no Zetaris, Nightshift or network
- [x] Meterless Nightshift is the primary AI provider; Nemotron model ID set in `litagent/config.py` (`nvidia/nemotron-3-ultra-550b-a55b`)
- [x] A Meterless Engine works in a user-facing feature with a passing test: World Model → `paper_map` and `GET /world/{run_id}` (`tests/test_world_model_conformance.py`: Meterless's 8 conformance checks; `tests/test_meterless_world_model.py`)
- [x] Zetaris running locally in Docker is the data layer: papers served from `litagent_db.papers` (`scripts/setup_zetaris.py`)
- [x] `logs/trace-<run_id>.jsonl` written for every run, with model names and no secrets (keys and tokens masked)
- [ ] Timeouts on every external call (done: model 90 s, Zetaris 45 s, OpenAlex 30 s, PDFs 20 s); full run within 5–10 minutes (`RUN_TIMEOUT_S` = 600 s per request) still to confirm on a complete real `/run`
- [x] `docker build` works and the container runs in sample mode; no model downloads at runtime (embedding model checked with `--network none`), no local GPU (image 761 MB, checked 24 Oct)
- [x] `.env.example` has placeholders only (plus local defaults such as the paper store's Docker password)
- [ ] `metadata.json` filled in and checked against the Submission Form Preview (filled; demo video and slide deck links still to add)
- [x] `pytest` passes

## Repo hygiene

- [x] No keys committed (`.env` is git-ignored and was never committed; `.env.example` has placeholders)
- [x] Data samples small (`data/sample/` is 568 KB); more topics come from `scripts/download_sample_data.py`
- [x] No sensitive or restricted data (OpenAlex metadata is CC0)
- [x] Licence chosen after checking the Official Rules (IP section): Apache-2.0, `LICENSE`

## Judging criteria (100 points)

| Criterion | Points | Our evidence |
| --- | --- | --- |
| Impact: real problem, clear user | 30 | Research students starting a literature review: one question gives a map of the papers that answer it, the work around it, how papers connect and what is still open, in minutes instead of days, with every claim tied to a quote they can check |
| Technical: implementation, reliability, architecture | 20 | Five agents exchanging typed Pydantic models; independent verification and grading after each finding stage; bounded retries, timeouts and token budgets; partial results instead of crashes; 517 pytest tests passed on 27 Oct (11.66 s), plus browser tests; `docs/agents/`, ARCHITECTURE.md |
| Innovation | 15 | Every connection and gap must quote both papers verbatim (checked in code) and pass an independent check; abstaining is a valid result; gaps are checked against the literature (OpenAlex coverage search) and unverified novelty is marked as such |
| Demo: explains itself | 15 | Live activity feed and Reasoning tab (each agent's steps, marked code / LLM / human, retries in orange); "Who made this, and why" on every paper, cluster, connection and gap |
| Product & UX | 10 | One question box with Fast / Pro modes, paper review before the map, a map that builds itself (clusters → Graph 1 → Graph 2), paper names on hover, foldable panels, versions and rollback, thumbs-up/down feedback and a draggable feedback assistant that revises the graph |
| Sponsor Tech | 10 | `docs/sponsor-tech.md`: Nightshift for every model call, Nemotron 3 Ultra for every producer and DeepSeek for every check, Zetaris as the shared paper store, Meterless World Model (8/8 conformance checks), Cursor project rules |

Ties go to the higher Impact score, then the earlier submission.

## Things judges look for (onboarding deck)

- [x] Agents that act, not just describe: they search, choose papers, group them, and write and check findings
- [x] Critique, retries and recovery visible: grades and redos, verifier rejections, retried and halved model calls, all in the Reasoning tab
- [x] Traces showing how the agent got its answer (`logs/trace-*.jsonl`, also served as `GET /runs/{id}/events`)
- [x] An output someone could actually use: the map, its quotes and the review page
