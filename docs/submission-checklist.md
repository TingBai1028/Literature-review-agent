# Submission checklist

**Deadline: 27 October 2026, 23:45 UTC** (= 28 October, 10:45 am Sydney time). Submit on HackOS. The team locks at first submission.

Source: participant onboarding deck. Final requirements are in the Official Rules on the event page; check them before submitting.

## Required items

- [ ] **Demo video**: 1–4 minutes, agent in action
- [ ] **Slide deck**: problem, user, solution, architecture
- [ ] **GitHub repository**: README with run instructions (Colab links if used)
- [ ] **Sponsor tech explanation**: Zetaris, Meterless, Cursor, NVIDIA → `docs/sponsor-tech.md`
- [ ] **Pre-existing components** declared → `docs/pre-existing-components.md`
- [ ] **Project details**: name, description, team members, track (Track 02)

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
- [ ] Traces showing how the agent got its answer (`runs/*.jsonl`)
- [ ] An output someone could actually use
