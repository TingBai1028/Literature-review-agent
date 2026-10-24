"""3. Clusterer agent. Spec: docs/agents/clusterer.md

Embeds each paper (title + abstract), mean-centers the run's embeddings (all papers share the topic,
so the shared direction would otherwise dominate), groups papers by average-linkage on cosine
similarity (groups merge while their average similarity stays above the threshold, which avoids the
chaining of connected components), and labels every group in one LLM call. Groups smaller than
min_cluster_size are left out: the orchestrator records those papers as "unclustered".

On a redo, the grading agent's fix is passed to the labeller, and a fix that says the clusters are
too broad or too fragmented moves the similarity threshold (settings.cluster_threshold_step).
"""

from __future__ import annotations

import json
import os
import re
import time

import numpy as np
from pydantic import BaseModel, Field

from litagent.config import EFFORT_PROFILES, EMBEDDING_MAX_CHARS, EMBEDDING_MODEL, Effort, Settings
from litagent.integrations.llm import complete_json, load_prompt
from litagent.schemas import Cluster, Paper
from litagent.trace import current_trace

ABSTRACT_CHARS_FOR_LABELS = 300  # the labeller sees titles plus the start of each abstract

_embedder = None


class ClusterLabel(BaseModel):
    cluster_id: str
    label: str = Field(description="3-8 words naming the shared idea")
    rationale: str = Field(description="One sentence: why these papers belong together")
    coherent: bool = Field(default=True, description="False if the papers don't share one idea")


class ClusterLabels(BaseModel):
    labels: list[ClusterLabel]


def cluster(papers: list[Paper], effort: Effort, settings: Settings, fix: str | None = None) -> list[Cluster]:
    """`fix` is the grading agent's one suggested fix when the previous attempt failed."""
    if settings.sample_mode:
        return _fake_clusters(papers)
    if len(papers) < settings.min_cluster_size:
        return []

    threshold = adjust_threshold(settings.cluster_similarity_threshold, fix, settings.cluster_threshold_step)
    use_full_text = EFFORT_PROFILES[effort].use_full_text
    start = time.monotonic()
    embeddings = center(embed([_text_for(p, use_full_text) for p in papers]))
    embed_s = time.monotonic() - start
    groups = average_linkage(cosine_similarity_matrix(embeddings), threshold)
    kept = sorted((g for g in groups if len(g) >= settings.min_cluster_size), key=lambda g: (-len(g), g[0]))
    left_out = sum(len(g) for g in groups if len(g) < settings.min_cluster_size)
    _log("group papers", f"{len(kept)} groups, {left_out} papers unclustered",
         f"sizes {[len(g) for g in kept]}",
         f"average linkage, mean-centered cosine >= {threshold:.2f} ({EMBEDDING_MODEL}, {len(papers)} papers embedded in {embed_s:.1f} s)"
         + (f"; threshold moved by grader fix: {fix}" if threshold != settings.cluster_similarity_threshold else ""))

    drafts = [Cluster(id=f"C{i + 1}", label="", paper_ids=[papers[j].id for j in g], rationale="") for i, g in enumerate(kept)]
    return label_clusters(drafts, papers, settings, fix)


def label_clusters(drafts: list[Cluster], papers: list[Paper], settings: Settings, fix: str | None) -> list[Cluster]:
    """One LLM call labels every group. Groups the model calls incoherent are dropped (their papers
    become unclustered); a group the model skipped gets a fallback label so no papers are lost."""
    if not drafts:
        return []
    by_id = {p.id: p for p in papers}
    message = {"clusters": [
        {"cluster_id": c.id, "papers": [{"title": by_id[pid].title, "abstract_start": (by_id[pid].abstract or "")[:ABSTRACT_CHARS_FOR_LABELS]}
                                        for pid in c.paper_ids]}
        for c in drafts
    ]}
    if fix:
        message["fix_from_grader"] = fix
    result = complete_json(load_prompt("cluster_labeler"), json.dumps(message, ensure_ascii=False), ClusterLabels,
                           settings=settings, agent_name="clusterer")
    labels = {lab.cluster_id: lab for lab in result.labels}

    out, dropped, fallback = [], [], []
    for c in drafts:
        lab = labels.get(c.id)
        if lab is None:
            fallback.append(c.id)
            out.append(c.model_copy(update={"label": by_id[c.paper_ids[0]].title[:80],
                                            "rationale": "Grouped by similarity; the labeller gave no label"}))
        elif not lab.coherent:
            dropped.append(c.id)
        else:
            out.append(c.model_copy(update={"label": lab.label, "rationale": lab.rationale}))
    if dropped or fallback:
        _log("label clusters", f"{len(out)} labelled", f"dropped as incoherent: {dropped}; fallback label: {fallback}",
             "The labeller said these papers don't share one idea" if dropped else "Labeller skipped some groups")
    # Renumber so ids stay C1..Cn after drops
    return [c.model_copy(update={"id": f"C{i + 1}"}) for i, c in enumerate(out)]


def adjust_threshold(threshold: float, fix: str | None, step: float) -> float:
    """Clusters too broad -> stricter threshold (more, smaller groups); too fragmented or none -> looser."""
    if not fix:
        return threshold
    text = fix.lower()
    if re.search(r"too broad|split|too large|too big", text):
        return min(threshold + step, 0.99)
    if re.search(r"no clusters|too many|fragment|merge|too small|too detailed|lower the similarity", text):
        return max(threshold - step, -1.0)
    return threshold


def embed(texts: list[str]) -> np.ndarray:
    """Local ONNX embeddings (config.EMBEDDING_MODEL); loaded once per process."""
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding

        _embedder = TextEmbedding(EMBEDDING_MODEL, cache_dir=os.getenv("EMBEDDING_CACHE_DIR") or None)
    return np.array(list(_embedder.embed([t[:EMBEDDING_MAX_CHARS] for t in texts])))


def center(embeddings: np.ndarray) -> np.ndarray:
    """Normalize, then subtract the run's mean vector, so similarity reflects what separates papers
    within the topic rather than the topic they all share."""
    unit = embeddings / np.clip(np.linalg.norm(embeddings, axis=1, keepdims=True), 1e-12, None)
    return unit - unit.mean(axis=0)


def cosine_similarity_matrix(embeddings: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    unit = embeddings / np.clip(norms, 1e-12, None)
    return unit @ unit.T


def average_linkage(similarity: np.ndarray, threshold: float) -> list[list[int]]:
    """Agglomerative clustering: repeatedly merge the two groups with the highest average pairwise
    similarity, while that average is >= threshold. Returns groups of indices, each sorted."""
    n = similarity.shape[0]
    groups: list[list[int]] = [[i] for i in range(n)]
    sim = similarity.astype(float).copy()
    np.fill_diagonal(sim, -np.inf)
    active = np.ones(n, dtype=bool)
    while active.sum() > 1:
        masked = np.where(active[:, None] & active[None, :], sim, -np.inf)
        a, b = np.unravel_index(np.argmax(masked), masked.shape)
        if masked[a, b] < threshold:
            break
        size_a, size_b = len(groups[a]), len(groups[b])
        # Average similarity of the merged group to every other group (UPGMA update)
        sim[a, :] = (size_a * sim[a, :] + size_b * sim[b, :]) / (size_a + size_b)
        sim[:, a] = sim[a, :]
        sim[a, a] = -np.inf
        groups[a] = sorted(groups[a] + groups[b])
        active[b] = False
    return [groups[i] for i in range(n) if active[i]]


def _text_for(paper: Paper, use_full_text: bool) -> str:
    if use_full_text and paper.full_text:
        return paper.full_text  # TODO: long texts may need Meterless read_in_chunks first
    return f"{paper.title}. {paper.abstract or ''}"


def _log(action: str, decision: str, result: str, why: str) -> None:
    if trace := current_trace():
        trace.log("clusterer", action, decision, result, "grade clusters", why)


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
