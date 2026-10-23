"""3. Clusterer agent. Spec: docs/agents/clusterer.md

Embeds papers, groups those with cosine similarity >= threshold, and labels each group.
Normal / Medium use metadata (title + abstract); High / Ultra use full text.
"""

from __future__ import annotations

import numpy as np

from litagent.config import EFFORT_PROFILES, Effort, Settings
from litagent.schemas import Cluster, Paper


def cluster(papers: list[Paper], effort: Effort, settings: Settings, fix: str | None = None) -> list[Cluster]:
    """`fix` is the grading agent's one suggested fix when the previous attempt failed."""
    if settings.sample_mode:
        return _fake_clusters(papers)

    use_full_text = EFFORT_PROFILES[effort].use_full_text
    texts = [_text_for(p, use_full_text) for p in papers]
    embeddings = embed(texts)
    groups = group_by_threshold(cosine_similarity_matrix(embeddings), settings.cluster_similarity_threshold)

    # TODO: label each group with the LLM (prompts/cluster_labeler.md), passing `fix` if given.
    # TODO: decide what to do with single-paper groups (outliers): keep them for the Gap finder?
    raise NotImplementedError


def embed(texts: list[str]) -> np.ndarray:
    """TODO: pick an embedding model, e.g. SPECTER2 (trained on scientific papers) via sentence-transformers."""
    raise NotImplementedError


def cosine_similarity_matrix(embeddings: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    unit = embeddings / np.clip(norms, 1e-12, None)
    return unit @ unit.T


def group_by_threshold(similarity: np.ndarray, threshold: float) -> list[list[int]]:
    """Put papers in the same group when they are linked by similarity >= threshold (connected components)."""
    n = similarity.shape[0]
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if similarity[i, j] >= threshold:
                parent[find(i)] = find(j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def _text_for(paper: Paper, use_full_text: bool) -> str:
    if use_full_text and paper.full_text:
        return paper.full_text  # TODO: long texts may need Meterless read_in_chunks first
    return f"{paper.title}. {paper.abstract or ''}"


def _fake_clusters(papers: list[Paper]) -> list[Cluster]:
    """Sample mode: split papers round-robin into 3 placeholder groups (no embeddings, no LLM)."""
    k = 3
    return [
        Cluster(
            id=f"C{i + 1}", label=f"Sample theme {i + 1}", paper_ids=[p.id for p in papers[i::k]],
            rationale="Sample mode: placeholder grouping, not real clustering",
        )
        for i in range(k)
    ]
