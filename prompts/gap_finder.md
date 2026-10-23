# Gap finder prompt

You are given related papers from one cluster.

1. Identify what hasn't been studied yet: an untried combination of methods and settings, an open problem the authors name in their limitations or future work, or a population or dataset nobody has tested.
2. Support each gap with quotes from the papers that border it.
3. Explain in one sentence why the gap matters.
4. Don't report a gap just because these few papers don't cover it; it must follow from what the papers say.
5. If a `fix` from the grading agent is given, apply it.

## Output

JSON list matching the `Gap` schema.

<!-- TODO: add examples -->
