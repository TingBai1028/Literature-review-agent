# Sponsor technology

Required in the submission: how we used Meterless (Nightshift + an Engine), Zetaris, NVIDIA and, optionally, Cursor. Sponsor Tech is worth 10 of 100 points, and judges reward "sponsor tech used where it helps". Zetaris and Meterless are required in every submission.

## Meterless Nightshift: primary AI provider

- **What it does for us:** every LLM call (Planner, cluster labels, Connection finder, Gap finder, grading agent) goes through Nightshift. It accepts OpenAI-format requests, so `complete_json` uses the official OpenAI client with `base_url=METERLESS_BASE_URL` and `api_key=METERLESS_RUNTIME_TOKEN`.
- **Model:** Nemotron 3 Ultra (`nvidia/nemotron-3-ultra-550b-a55b`) through Nightshift's NVIDIA provider, set explicitly in `litagent/config.py` (`NIGHTSHIFT_MODEL`), no automatic routing, so a non-NVIDIA model is never picked. Chosen after testing every Nemotron model Nightshift lists (24 Oct): Ultra answered quickly; Nemotron 3 Super and Llama 3.1 Nemotron Ultra aren't available to our NVIDIA account, Llama 3.3 Nemotron Super is retired, and Nightshift excludes 3.5 Super VL for unreliable responses. Fallback: Nemotron 3.5 Lightning. `<think>` blocks are removed before JSON parsing in case reasoning is returned.
- **Where in the code:** `litagent/integrations/llm.py` (JSON output validated with Pydantic, one retry with the validation error, 60 s timeout, model name + token usage logged per call)
- **Screenshot / evidence:** TODO

## Zetaris: shared paper data layer

- **What it does for us:** TODO. Draft: the Retriever writes every paper it finds to Zetaris; every later agent reads papers through Zetaris instead of calling the APIs again, so all agents work from one source of truth.
- **Where in the code:** `litagent/integrations/zetaris.py`. `ZetarisRestClient.run_sql` calls the documented REST API (`POST {ZETARIS_REST_URL}/sql-editor/sqls/run`, same as `scripts/zetaris_sql.py` in [zetaris/getting-started](https://github.com/zetaris/getting-started)) with a 45 s timeout. TODO: create the papers table and implement `save_papers` / `get_papers` on top of it.
- **Settings:** `ZETARIS_REST_URL`, `ZETARIS_ORG_ID`, `ZETARIS_API_KEY` (use `host.docker.internal` from inside our container).
- **Stretch goal:** join the user's own library (uploaded PDFs or a reference-manager export) with public metadata in one query, without copying private data.
- **Screenshot / evidence:** TODO

## Meterless: world model and Markovian engine

- **World model (our required working Meterless Engine feature):** each agent writes its findings (clusters, connections, gaps) to one shared graph; the next agent reads from it, and `/run` returns it as `output.paper_map`, which the front end renders as the paper map. Test: `tests/test_meterless_world_model.py`.
  - **Status:** `WorldModel` is currently our in-memory stand-in with the same interface. TODO: back it with the real World Model from the Resources tab; the test then covers the real engine. Until then, don't claim the engine itself is integrated.
- **Markovian engine:** TODO. Draft: reads full-text PDFs in chunks at High / Ultra effort, carrying compressed state between chunks.
- **Where in the code:** `litagent/integrations/meterless.py`
- **Screenshot / evidence:** TODO

## NVIDIA

- **Nemotron through Nightshift:** all agents use Nemotron 3.5 Super VL, connected in Nightshift's Providers tab (the NVIDIA key lives there, never in our app or `.env`).
- **Evidence:** every LLM event in `logs/trace-<run_id>.jsonl` records the `model` that handled the request, as reported by Nightshift.
- No local GPU is used.

## Cursor (with SpaceX XAI) — optional

- TODO: how the team used it, if at all (e.g. project rules in `.cursor/rules/`, which parts were built with agent mode).
