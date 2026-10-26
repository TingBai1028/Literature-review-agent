"""Full-PDF vs metadata analysis per cluster, and cluster cards (spec H). Spec: docs/agents/clusterer.md

- H1/H2: after roles are assigned, full text is read only for main and foundation papers; side clusters stay
  metadata only (title, abstract, year, citations, references, keywords).
- H3: each cluster is summarised once into a card: numbers and keywords by code, a 3-5 sentence summary by one
  batched LLM call, from full-text passages for main/foundation and abstracts for side clusters.
"""

from __future__ import annotations

import json
from collections import Counter
from statistics import median

from litagent.cluster_labels import relevant_spans
from litagent.config import Settings
from openai import OpenAIError

from litagent.integrations.llm import LLMError, complete_json, load_prompt
from litagent.schemas import Cluster, ClusterCard, ClusterCardSummaries, Paper
from litagent.trace import current_trace

DEEP_ROLES = ("main", "foundation")


def full_text_ids(clusters: list[Cluster]) -> set[str]:
    """Papers analysed in full: the main and foundation clusters (spec H1)."""
    return {pid for c in clusters if getattr(c, "kind", None) in DEEP_ROLES for pid in c.paper_ids}


def read_role_full_text(papers: list[Paper], clusters: list[Cluster], settings: Settings) -> list[Paper]:
    """Download open-access full text for main and foundation papers only; side papers are never fetched (H2)."""
    from litagent.agents.retriever import attach_full_text

    deep = full_text_ids(clusters)
    wanted = [p for p in papers if p.id in deep]
    if settings.sample_mode or not wanted:
        return papers
    if trace := current_trace():
        trace.log("clusterer", "read full text", f"{len(wanted)} main and foundation papers", phase="start",
                  message=f"Reading full PDFs for the {len(wanted)} main and foundation papers; side clusters stay metadata only")
    fetched = {p.id: p for p in attach_full_text(wanted, settings)}
    out = [fetched.get(p.id, p) for p in papers]
    if trace := current_trace():
        got = sum(bool(fetched[pid].full_text) for pid in fetched)
        trace.log("clusterer", "read full text", f"{got} of {len(wanted)} papers", phase="done",
                  message=f"Full text for {got} of {len(wanted)} main and foundation papers; "
                          f"{len(papers) - len(wanted)} side papers analysed from metadata",
                  payload={"full_text_ids": sorted(pid for pid in fetched if fetched[pid].full_text)})
    return out


def build_cards(papers: list[Paper], clusters: list[Cluster], question: str, settings: Settings) -> list[ClusterCard]:
    by_id = {p.id: p for p in papers}
    deep = full_text_ids(clusters)
    cards = []
    for c in clusters:
        members = [by_id[pid] for pid in c.paper_ids if pid in by_id]
        years = [p.year for p in members if p.year]
        cites = [p.citation_count or 0 for p in members]
        words = Counter(k for d in getattr(c, "paper_details", []) for k in d.keywords)
        role = getattr(c, "kind", None) or "side"
        cards.append(ClusterCard(cluster_id=c.id, role=role, label=c.label, rationale=c.rationale,
            paper_ids=c.paper_ids, year_range=(min(years), max(years)) if years else None,
            citations={"median": float(median(cites)), "max": float(max(cites))} if cites else {},
            keywords=[k for k, _ in words.most_common(8)], summary="",
            analysis_depth="full_pdf" if role in DEEP_ROLES else "metadata",
            papers_with_full_text=sum(bool(p.full_text) for p in members if p.id in deep)))
    summaries = _summaries(cards, by_id, question, settings)
    for card in cards:
        card.summary = summaries.get(card.cluster_id) or f"{card.label}. {card.rationale}"
    if trace := current_trace():
        trace.log("clusterer", "cluster cards", f"{len(cards)} cards", phase="partial_result",
                  message=f"Summarised {len(cards)} clusters into cards (full text for main and foundation, "
                          "metadata for side clusters)",
                  payload={"cards": [{"cluster_id": c.cluster_id, "role": c.role, "analysis_depth": c.analysis_depth}
                                     for c in cards]})
    return cards


def _summaries(cards: list[ClusterCard], by_id: dict[str, Paper], question: str, settings: Settings) -> dict[str, str]:
    if settings.sample_mode:
        return {c.cluster_id: f"Sample mode: placeholder summary of {len(c.paper_ids)} papers, "
                               f"{'from full text' if c.analysis_depth == 'full_pdf' else 'from metadata'}; "
                               "no model read them." for c in cards}
    chars = settings.cluster_card_text_chars
    def text(paper: Paper, deep: bool) -> str:
        if deep and paper.full_text:
            return " ".join(s["quote"] for s in relevant_spans(paper.full_text, f"{question} {paper.title}", chars, chars))
        return (paper.abstract or "")[:chars]
    payload = {"task_version": "cluster-cards-v1", "question": question,
               "clusters": [{"cluster_id": c.cluster_id, "role": c.role, "label": c.label,
                             "analysis_depth": c.analysis_depth,
                             "papers": [{"id": pid, "title": by_id[pid].title, "year": by_id[pid].year,
                                         "text": text(by_id[pid], c.analysis_depth == "full_pdf")}
                                        for pid in sorted(c.paper_ids, key=lambda i: -(by_id[i].citation_count or 0))
                                        [:settings.cluster_card_papers]]} for c in cards]}
    try:
        out = complete_json(load_prompt("cluster_cards"), json.dumps(payload, ensure_ascii=False), ClusterCardSummaries,
                            settings=settings, agent_name="clusterer")
    except (LLMError, OpenAIError) as error:
        # A missing summary must not cost the whole map: cards fall back to the label and rationale.
        if trace := current_trace():
            trace.log("clusterer", "cluster cards", "summaries unavailable", why=f"{type(error).__name__}: {error}",
                      message="Cluster card summaries failed; cards use each cluster's label and rationale")
        return {}
    known = {c.cluster_id for c in cards}
    return {s.cluster_id: s.summary.strip() for s in out.cards if s.cluster_id in known}


def compact(cards: list[ClusterCard]) -> list[dict]:
    """What a downstream agent sees of each cluster (spec H4)."""
    return [{"cluster_id": c.cluster_id, "role": c.role, "label": c.label, "summary": c.summary,
             "year_range": c.year_range, "keywords": c.keywords, "analysis_depth": c.analysis_depth} for c in cards]
