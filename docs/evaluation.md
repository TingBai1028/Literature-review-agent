# Evaluation

Two kinds of evaluation:

- **Runtime (inside the agent):** grading agents and human reviews check every run. See `ARCHITECTURE.md`.
- **Offline (this file):** a fixed set of test topics we run the whole agent on, to check whether changes make it better.

## Test topics

Topics with a good published survey paper, which acts as a rough answer key (its sections ≈ clusters, its open problems ≈ gaps). Listed in `evals/topics.yaml`.

## Metrics

| Metric | How we measure it | Result (TODO) |
| --- | --- | --- |
| Citation accuracy | Share of quotes that actually support their claim (hand-check a sample) | |
| Cluster agreement | How well our clusters match the survey's sections | |
| Gap recall | Share of the survey's open problems our agent found | |
| Grading pass rate | Share of stages passing on the first attempt | |

## Results

TODO: table per topic, then one sentence for the README and slide deck.
