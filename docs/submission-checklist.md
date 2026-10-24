# Submission checklist

**Deadline: 27 October 2026, 23:45 UTC** (= 28 October, 10:45 am Sydney time). Submit on HackOS. The team locks at first submission.

Source: participant onboarding deck. Final requirements are in the Official Rules on the event page; check them before submitting.

## Required items

- [ ] **Demo video**: 1–4 minutes, agent in action
- [ ] **Slide deck**: problem, user, solution, architecture
- [ ] **GitHub repository**: README with run instructions (Colab links if used)
- [ ] **Sponsor tech explanation**: Meterless (Nightshift + World Model), Zetaris, NVIDIA, Cursor (optional) → `docs/sponsor-tech.md`
- [ ] **Pre-existing components** declared → `docs/pre-existing-components.md`
- [ ] **Project details**: name, description, team members, track (Track 02)

## Technical execution requirements

- [ ] Public GitHub repo
- [ ] `run.py` at the repo root; `POST /run` returns `success` / `error` JSON (never crashes silently)
- [ ] At least 3 examples: `input_examples/` + matching `output_examples/` (sample mode)
- [ ] `SAMPLE_MODE=true` runs end to end with no Zetaris, Nightshift or network
- [ ] Meterless Nightshift is the primary AI provider; Nemotron model ID set in `litagent/config.py`
- [x] A Meterless Engine works in a user-facing feature with a passing test: World Model → `paper_map` and `GET /world/{run_id}` (`tests/test_world_model_conformance.py`: Meterless's 8 conformance checks; `tests/test_meterless_world_model.py`)
- [x] Zetaris running locally in Docker is the data layer: papers served from `litagent_db.papers` (`scripts/setup_zetaris.py`)
- [ ] `logs/trace-<run_id>.jsonl` written for every run, with model names and no secrets
- [ ] Timeouts on every external call; full run within 5–10 minutes (`RUN_TIMEOUT_S`)
- [x] `docker build` works and the container runs in sample mode; no model downloads at runtime (embedding model checked with `--network none`), no local GPU (image 761 MB, checked 24 Oct)
- [ ] `.env.example` has placeholders only
- [ ] `metadata.json` filled in and checked against the Submission Form Preview
- [ ] `pytest` passes

## Repo hygiene

- [ ] No keys committed (`.env` is git-ignored; `.env.example` has placeholders)
- [ ] Data samples small; large data comes from `scripts/download_sample_data.py`
- [ ] No sensitive or restricted data
- [ ] Licence chosen after checking the Official Rules (IP section)

## Judging criteria (100 points)

| Criterion | Points | Our evidence (TODO) |
| --- | --- | --- |
| Impact: real problem, clear user | 30 | |
| Technical: implementation, reliability, architecture | 20 | Grading loops, retries, trace logs |
| Innovation | 15 | |
| Demo: explains itself | 15 | |
| Product & UX | 10 | Chat box, effort levels, paper map |
| Sponsor Tech | 10 | `docs/sponsor-tech.md` |

Ties go to the higher Impact score, then the earlier submission.

## Things judges look for (onboarding deck)

- [ ] Agents that act, not just describe
- [ ] Critique, retries and recovery visible in the demo
- [ ] Traces showing how the agent got its answer (`logs/trace-*.jsonl`)
- [ ] An output someone could actually use
