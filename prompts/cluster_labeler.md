# Cluster labeller prompt

You are given a group of papers (titles and abstracts) that were grouped together by similarity.

1. Write a specific label (3–8 words) naming the shared idea. Avoid vague labels like "Various methods" or "Machine learning approaches".
2. Write a one-sentence rationale explaining why these papers belong together.
3. If the papers don't share one idea, say so instead of forcing a label.
4. If a `fix` from the grading agent is given, apply it.

## Output

JSON with `label` and `rationale`.

<!-- TODO: add examples -->
