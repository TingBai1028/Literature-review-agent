"""Entity resolution with banded thresholds (spec: AGENTS.md §7.1, merge detection).

    similarity >= 0.85            -> auto-merge   (0.85 exactly merges)
    0.82 <= similarity < 0.85     -> operator review queue (0.82 exactly queues)
    similarity < 0.82             -> new entity

Similarity = 1 - Levenshtein distance / max length, on normalized names.
Python port of engines/world-model/reference/src/resolve.ts (Meterless, Apache-2.0).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from rapidfuzz.distance import Levenshtein

from litagent.integrations.world_model.stable_ids import normalize_name

Decision = Literal["auto-merge", "review", "new"]
AUTO_MERGE_AT = 0.85
REVIEW_LOWER = 0.82


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a or not b:
        return len(a) or len(b)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = curr
    return prev[-1]


def name_similarity(raw_a: str, raw_b: str) -> float:
    return normalized_similarity(normalize_name(raw_a), normalize_name(raw_b))


def normalized_similarity(a: str, b: str, floor: float = 0.0) -> float:
    """Similarity of two already-normalized names; 0.0 when below `floor`.

    Uses rapidfuzz (C) for speed: the same 1 - distance / max length as `levenshtein` above
    (tests check they agree), but resolving ~1,500 authors means about a million comparisons."""
    if not a and not b:
        return 1.0
    return Levenshtein.normalized_similarity(a, b, score_cutoff=floor or None)


def decide(similarity: float, auto_merge_at: float = AUTO_MERGE_AT, review_lower: float = REVIEW_LOWER) -> Decision:
    if similarity >= auto_merge_at:
        return "auto-merge"
    if similarity >= review_lower:
        return "review"
    return "new"


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    """Clustering gate for the ingest pipeline: entity-overlap Jaccard >= 0.5 co-clusters two observations."""
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    return inter / (len(sa) + len(sb) - inter)
