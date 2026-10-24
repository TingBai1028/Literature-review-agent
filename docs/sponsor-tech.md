# Sponsor technology

Required in the submission: how we used Meterless (Nightshift + an Engine), Zetaris, NVIDIA and, optionally, Cursor. Sponsor Tech is worth 10 of 100 points, and judges reward "sponsor tech used where it helps". Zetaris and Meterless are required in every submission.

## Meterless Nightshift: primary AI provider

- **What it does for us:** every LLM call (Planner, cluster labels, Connection finder, Gap finder, grading agent) goes through Nightshift. It accepts OpenAI-format requests, so `complete_json` uses the official OpenAI client with `base_url=METERLESS_BASE_URL` and `api_key=METERLESS_RUNTIME_TOKEN`.
- **Model:** Nemotron 3 Ultra (`nvidia/nemotron-3-ultra-550b-a55b`) through Nightshift's NVIDIA provider, set explicitly in `litagent/config.py` (`NIGHTSHIFT_MODEL`), no automatic routing, so a non-NVIDIA model is never picked. Chosen after testing every Nemotron model Nightshift lists (24 Oct): Ultra answered quickly; Nemotron 3 Super and Llama 3.1 Nemotron Ultra aren't available to our NVIDIA account, Llama 3.3 Nemotron Super is retired, and Nightshift excludes 3.5 Super VL for unreliable responses. Fallback: Nemotron 3.5 Lightning. `<think>` blocks are removed before JSON parsing in case reasoning is returned.
- **Where in the code:** `litagent/integrations/llm.py` (JSON output validated with Pydantic, one retry with the validation error, 60 s timeout, model name + token usage logged per call)
- **Screenshot / evidence:** TODO

## Zetaris: shared paper data layer

- **What it does for us:** the Retriever writes each run's papers to our Postgres paper store (`docker-compose.yml`), which Zetaris serves as the `litagent_db` data source. Every later agent reads papers back with Zetaris SQL (`SELECT … FROM litagent_db.papers WHERE run_id = …`) instead of calling the APIs again, so all agents work from one source of truth. Every query is logged with its row count. If Zetaris fails mid-run, the run continues on an in-memory copy with a warning.
- **Where in the code:** `litagent/integrations/zetaris.py`. `ZetarisRestClient.run_sql` calls the documented REST API (`POST {ZETARIS_REST_URL}/sql-editor/sqls/run`, same as `scripts/zetaris_sql.py` in [zetaris/getting-started](https://github.com/zetaris/getting-started)) with a 45 s timeout. Setup: `scripts/setup_zetaris.py` creates the table, registers the data source and table (`CREATE DATASOURCE`, `REGISTER DATASOURCE TABLE`) and checks a live round trip.
- **Settings:** `ZETARIS_REST_URL`, `ZETARIS_ORG_ID`, `ZETARIS_API_KEY` (use `host.docker.internal` from inside our container).
- **Stretch goal:** join the user's own library (uploaded PDFs or a reference-manager export) with public metadata in one query, without copying private data.
- **Screenshot / evidence:** TODO

## Meterless: world model and Markovian engine

- **World Model (our required working Meterless Engine):** Meterless ships the World Model as an implementation spec (`engines/world-model/AGENTS.md`) with a TypeScript reference and a conformance suite. We implemented it in Python (`litagent/integrations/world_model/`), ported from the reference: event-sourced store with an audit log, content-derived stable IDs, entity resolution with merge bands and an operator review queue, bitemporal relationships, facts with a conflict policy, and the canonical ingest pipeline.
  - **Conformance:** `tests/test_world_model_conformance.py` ports all 8 checks of Meterless's suite (stable IDs, merge bands, provenance, idempotent ingest, bitemporal edges, audit order), plus parity tests: IDs and similarity scores match values computed by running Meterless's own reference (their reference passes their suite 8/8; ours passes the same checks).
  - **How the agents use it (user-facing):** the run is a context and each planning attempt a child context. Papers, authors, clusters and gaps are entities; `found-by`, `authored-by`, `member-of`, `connects-to` (with evidence quotes) and `between` are relationships; grader scores are facts. Every write carries provenance (agent, run, time). Later agents read from it (`read_clusters`, `cluster_context`, `shared_authors`); `/run` returns it as `output.paper_map` for the paper map, and `GET /world/{run_id}` returns the whole saved world (entities, relationships, facts, review queue, audit log) from `logs/world-<run_id>.json`. Tests: `tests/test_meterless_world_model.py`.
  - **Two typed-graph choices** (spec §6.1 allows per-type constraints): `authored-by`, `connects-to` and `between` keep several current targets instead of superseding; and authors never auto-merge on name similarity. On real OpenAlex data the default 0.85 band merged different people with short names ("Liang Li" / "Xiang Li"), so author near-matches go to the operator review queue (spec §7.1: never auto-destructive). Identical normalized names ("José García" / "Jose Garcia") are still one author.
- **Markovian engine:** TODO. Draft: reads full-text PDFs in chunks at High / Ultra effort, carrying compressed state between chunks.
- **Where in the code:** `litagent/integrations/world_model/` (engine), `litagent/integrations/meterless.py` (how litagent uses it)
- **Screenshot / evidence:** TODO (e.g. `GET /world/<run_id>` output, or the paper map)

## NVIDIA

- **Nemotron through Nightshift:** all agents use Nemotron 3 Ultra, connected in Nightshift's Providers tab (the NVIDIA key lives there, never in our app or `.env`).
- **Evidence:** every LLM event in `logs/trace-<run_id>.jsonl` records the `model` that handled the request, as reported by Nightshift.
- No local GPU is used.

## Cursor (with SpaceX XAI) — optional

- TODO: how the team used it, if at all (e.g. project rules in `.cursor/rules/`, which parts were built with agent mode).
