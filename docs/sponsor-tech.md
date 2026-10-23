# Sponsor technology

Required in the submission: how we used Zetaris, Meterless, Cursor and NVIDIA. Sponsor Tech is worth 10 of 100 points, and judges reward "sponsor tech used where it helps". Zetaris and Meterless are required in every submission.

## Zetaris: shared paper data layer

- **What it does for us:** TODO. Draft: the Retriever writes every paper it finds to Zetaris; every later agent reads papers through Zetaris instead of calling the APIs again, so all agents work from one source of truth.
- **Where in the code:** `litagent/integrations/zetaris.py`
- **Stretch goal:** join the user's own library (uploaded PDFs or a reference-manager export) with public metadata in one query, without copying private data.
- **Screenshot / evidence:** TODO

## Meterless: world model and Markovian engine

- **World model:** TODO. Draft: each agent writes its findings (clusters, connections, gaps) to one shared graph; the next agent reads from it, and the front end renders it as the paper map.
- **Markovian engine:** TODO. Draft: reads full-text PDFs in chunks at High / Ultra effort, carrying compressed state between chunks.
- **Where in the code:** `litagent/integrations/meterless.py`
- **Screenshot / evidence:** TODO

## Cursor (with SpaceX XAI)

- TODO: how the team used it (e.g. project rules in `.cursor/rules/`, which parts were built with agent mode).

## NVIDIA

- TODO: used for compute? If not used, say so.
