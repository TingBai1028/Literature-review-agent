"""Offline inputs for sample mode, made by scripts/build_sample_gap_inputs.py (no network or embedding model)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from litagent.schemas import Paper

SAMPLE_SIMILARITY_DIR = Path(__file__).resolve().parents[1] / "data" / "sample" / "similarity"


def sample_similarity(papers: list[Paper]) -> np.ndarray | None:
    """The stored embedding similarity of these papers, or None when no sample file covers all of them."""
    for path in sorted(SAMPLE_SIMILARITY_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        index = {pid: i for i, pid in enumerate(data["paper_ids"])}
        if all(p.id in index for p in papers):
            rows = [index[p.id] for p in papers]
            return np.asarray(data["similarity"], dtype=float)[np.ix_(rows, rows)]
    return None


def sample_relevance(papers: list[Paper], question: str) -> np.ndarray:
    """TF-IDF cosine of each paper to the question, scaled so the most relevant paper scores 1."""
    from sklearn.feature_extraction.text import TfidfVectorizer

    try:
        matrix = TfidfVectorizer(stop_words="english").fit_transform([question] + [f"{p.title}. {p.abstract or ''}" for p in papers])
    except ValueError:  # empty vocabulary
        return np.zeros(len(papers))
    scores = (matrix[1:] @ matrix[0].T).toarray().ravel()
    return scores / scores.max() if scores.max() > 0 else scores
