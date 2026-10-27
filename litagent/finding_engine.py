"""Shared bounded source contexts, pair selection, validation and exact-input task caches."""

from __future__ import annotations

import itertools
import json
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from openai import OpenAIError

from litagent.cluster_audit import duplicate_components, partition_indices
from litagent.cluster_labels import evidence_source, relevant_spans, source_spans
from litagent.cluster_state import digest, file_hash
from litagent.config import Settings
from litagent.integrations.embeddings import embed_documents
from litagent.integrations.llm import LLMError, TokenBudgetExceeded, complete_json, load_prompt
from litagent.schemas import (Evidence, FindingAudit, FindingCacheRecord, FindingDependency,
                             FindingVerifications, Paper, QuestionCluster)
from litagent.similarity import paper_similarity
from litagent.trace import current_trace


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class FindingContext:
    question: str | None = None
    feedback: str | None = None
    similarity: np.ndarray | None = None
    use_full_text: bool = False
    # Spec H2: when set, only these papers (main and foundation) are read in full; all others use metadata.
    full_text_ids: set[str] | None = None
    cards: list = field(default_factory=list)  # cluster cards (spec H3) the gap finder reads as context
    deadline: float | None = None
    cache: dict[str, FindingCacheRecord] = field(default_factory=dict)
    dependencies: dict[str, FindingDependency] = field(default_factory=dict)
    audits: list[FindingAudit] = field(default_factory=list)
    partial_connections: list = field(default_factory=list)
    partial_gaps: list = field(default_factory=list)


def check_deadline(context: FindingContext) -> None:
    if context.deadline is not None and time.monotonic() >= context.deadline:
        raise TokenBudgetExceeded("Finding analysis time limit reached")


def prepare(papers, clusters, settings: Settings, context: FindingContext | None) -> FindingContext:
    partition_indices(papers, clusters)
    if (min(settings.finding_source_chars, settings.finding_span_chars, settings.finding_min_quote_chars,
            settings.connection_within_pairs_per_cluster, settings.connection_max_pairs_per_paper,
            settings.gap_max_per_cluster, settings.gap_candidate_multiplier, settings.gap_coverage_results,
            settings.gap_coverage_hits_per_query, settings.gap_coverage_source_chars) < 1
            or min(settings.connection_max_within_pairs, settings.connection_max_between_pairs,
                   settings.finding_validation_retries) < 0
            or settings.finding_span_chars < settings.finding_min_quote_chars
            or not 0 <= settings.connection_similarity_min <= 1
            or not 0 <= settings.gap_similarity_min <= settings.gap_similarity_max <= 1
            or not np.isfinite(settings.gap_coverage_ttl_s) or settings.gap_coverage_ttl_s < 0):
        raise ValueError("Invalid finding limits, thresholds or coverage cache lifetime")
    context = context or FindingContext()
    context.question = context.question or next((c.question for c in clusters if isinstance(c, QuestionCluster)), None)
    if context.deadline is None:
        context.deadline = time.monotonic() + settings.run_timeout_s
    check_deadline(context)
    if context.similarity is None:
        texts = [p.full_text if context.use_full_text and p.full_text else f"{p.title}. {p.abstract or ''}" for p in papers]
        context.similarity = paper_similarity(papers, embed_documents(texts, settings), settings).combined
    matrix = np.asarray(context.similarity, dtype=float)
    if (matrix.shape != (len(papers), len(papers)) or not np.isfinite(matrix).all()
            or not np.allclose(matrix, matrix.T) or (matrix < -1 - 1e-8).any() or (matrix > 1 + 1e-8).any()):
        raise ValueError("Finding similarity matrix must match the input paper rows")
    context.similarity = matrix
    return context


def sources(papers: list[Paper], settings: Settings, context: FindingContext, *, limit: int | None = None) -> dict:
    out = {}
    for paper in papers:
        deep = context.full_text_ids is None or paper.id in context.full_text_ids
        selected = (paper.full_text if context.use_full_text and paper.full_text and deep
                    else f"{paper.title}. {paper.abstract or ''}")
        field_name, text = evidence_source(paper, selected)
        if field_name == "title" or len(text.strip()) < settings.finding_min_quote_chars:
            continue
        budget = limit or settings.finding_source_chars
        spans = (relevant_spans(text, f"{context.question or ''} {paper.title}", budget, settings.finding_span_chars)
                 if field_name == "full_text" else source_spans(text[:budget], settings.finding_span_chars))
        out[paper.id] = {"id": paper.id, "title": paper.title, "source_field": field_name,
                         "spans": [{"span_id": s["span_id"], "quote": s["quote"]} for s in spans]}
    return out


def choose_pairs(stage: str, papers, clusters, settings: Settings, context: FindingContext, body_ids: set[str]):
    """Connection finder pairs. The Gap finder selects its own candidates (gap_finder.candidate_pairs)."""
    owner = {pid: c for c in clusters for pid in c.paper_ids}
    dup = {pid: n for n, group in enumerate(duplicate_components(papers)) for pid in group}
    indices = {p.id: i for i, p in enumerate(papers)}
    references = {p.id: set(p.references or ()) for p in papers}
    skipped, within, between = 0, [], []
    for a, b in itertools.combinations(sorted(body_ids), 2):
        if dup[a] == dup[b]:
            skipped += 1
            continue
        pair = make_pair(a, b, owner, references, float(context.similarity[indices[a], indices[b]]))
        # A citation from the OpenAlex reference lists is a concrete link (relation directly_cites), so the pair
        # is a candidate even below the similarity floor.
        if pair["similarity"] < settings.connection_similarity_min and pair["cited"] is None:
            continue
        (within if pair["kind"] == "within_cluster" else between).append(pair)
    order = lambda p: (not p["main"], p["cited"] is None, -p["similarity"], p["paper_ids"])
    within.sort(key=order)
    between.sort(key=order)
    selected, counts, cluster_counts, seen_cross = [], Counter(), Counter(), set()
    for pool, maximum in ((within, settings.connection_max_within_pairs), (between, settings.connection_max_between_pairs)):
        used = 0
        for pair in pool:
            if used >= maximum:
                break
            cid = pair["cluster_ids"][0]
            if any(counts[p] >= settings.connection_max_pairs_per_paper for p in pair["paper_ids"]):
                continue
            if pair["kind"] == "within_cluster" and cluster_counts[cid] >= settings.connection_within_pairs_per_cluster:
                continue
            if pair["kind"] == "between_clusters" and tuple(pair["cluster_ids"]) in seen_cross:
                continue
            selected.append(pair)
            counts.update(pair["paper_ids"])
            cluster_counts[cid] += 1
            seen_cross.add(tuple(pair["cluster_ids"]))
            used += 1
    if trace := current_trace():
        trace.log(stage + "_finder", "select scientific pairs", f"{len(selected)} bounded comparisons",
                  result={"duplicate_pairs_skipped": skipped, "papers_with_body": len(body_ids), "pairs": selected},
                  why="Main-cluster pairs first, then citation links, then cosine; original-source availability, "
                      "duplicate-study exclusion and per-paper/group caps")
    return selected, skipped


def make_pair(a: str, b: str, owner: dict, references: dict, similarity: float) -> dict:
    """The connection finder's description of one paper pair (a < b): clusters, kind, similarity and any citation."""
    cited = b if b in references[a] else a if a in references[b] else None
    same = owner[a].id == owner[b].id
    return {"pair_id": "PAIR-" + digest([a, b])[:16], "paper_ids": [a, b], "cluster_ids": sorted({owner[a].id, owner[b].id}),
            "kind": "within_cluster" if same else "between_clusters", "similarity": similarity,
            "citation": f"{a if cited == b else b} cites {cited}" if cited else None, "cited": cited,
            "main": any(getattr(owner[pid], "kind", "side") == "main" for pid in (a, b))}


def pair_payload(pair, source_map, clusters) -> dict:
    by_id = {c.id: c for c in clusters}
    return {**{k: v for k, v in pair.items() if k != "main"},
            "clusters": [{"id": cid, "kind": getattr(by_id[cid], "kind", "topic"), "label": by_id[cid].label,
                          "paper_ids": sorted(by_id[cid].paper_ids)} for cid in pair["cluster_ids"]],
            "papers": [source_map[pid] for pid in pair["paper_ids"]]}


def exact_ids(received, expected, noun: str) -> None:
    if len(received) != len(set(received)) or set(received) != set(expected):
        raise ValueError(f"Return each supplied {noun} exactly once; expected {sorted(expected)}")


def resolve_evidence(refs, source_map, expected_ids: set[str], settings: Settings) -> list[Evidence]:
    evidence, seen = [], set()
    for ref in refs:
        if ref.paper_id not in expected_ids or ref.paper_id not in source_map:
            raise ValueError("Evidence must refer to an original supplied target paper")
        spans = {s["span_id"]: s["quote"] for s in source_map[ref.paper_id]["spans"]}
        if ref.span_id not in spans or len(spans[ref.span_id].strip()) < settings.finding_min_quote_chars:
            raise ValueError("Evidence must select a sufficiently long original source span")
        if (ref.paper_id, ref.span_id) in seen:
            raise ValueError("Duplicate source reference")
        seen.add((ref.paper_id, ref.span_id))
        evidence.append(Evidence(paper_id=ref.paper_id, quote=spans[ref.span_id]))
    if {e.paper_id for e in evidence} != expected_ids:
        raise ValueError("A supporting quote is required from BOTH target papers")
    return evidence


def request(prompt: str, payload: dict, schema, validate, settings: Settings, context: FindingContext, stage: str,
            retry_timeout: bool = True, model: str | None = None):
    message = dict(payload)
    for attempt in range(settings.finding_validation_retries + 1):
        check_deadline(context)
        try:
            output = complete_json(load_prompt(prompt), json.dumps(message, ensure_ascii=False), schema,
                                   settings=settings, agent_name=stage + "_finder", retry_timeout=retry_timeout,
                                   model=model)
        except OpenAIError as error:
            raise LLMError(f"{stage} provider request failed ({type(error).__name__})") from error
        try:
            validate(output)
            return output
        except ValueError as error:
            if trace := current_trace():
                trace.log(stage + "_finder", "validate source references", "rejected", why=str(error),
                          next_step="bounded repair" if attempt < settings.finding_validation_retries else "raise")
            if attempt == settings.finding_validation_retries:
                raise LLMError(f"{stage} evidence failed bounded source validation: {error}") from error
            message.update(validation_error=str(error), rejected_proposal=output.model_dump(mode="json"))


def verify(proposals: list[dict], settings: Settings, context: FindingContext, stage: str) -> dict:
    if not proposals:
        return {}
    payload = {"task_version": stage + "-verify-v1", "question": context.question, "claims": proposals}
    def validate(output):
        exact_ids([v.pair_id for v in output.verdicts], [p["pair_id"] for p in proposals], "pair_id")
    output = request(stage + "_verify", payload, FindingVerifications, validate, settings, context, stage,
                     model=settings.grader_model)
    return {v.pair_id: v for v in output.verdicts}


def cache_key(stage: str, payload: dict, schema, settings: Settings) -> str:
    names = (["gap_finder", "gap_coverage", "gap_grader", "gap_explicit"] if stage == "gaps"
             else ["connection_finder", "connections_verify"])
    params = {k: v for k, v in vars(settings).items() if k.startswith(("finding_", "connection_", "gap_"))}
    files = [Path(__file__), Path(__file__).parent / "agents" / (stage[:-1] + "_finder.py")]
    if stage == "gaps":
        files += [Path(__file__).parent / "tools" / name for name in ("openalex.py", "semantic_scholar.py", "search_store.py")]
    return digest({"payload": payload, "settings": params, "model": settings.llm_model, "grader_model": settings.grader_model,
                   "prompts": {name: load_prompt(name) for name in names}, "schema": schema.model_json_schema(),
                   "verification_schema": FindingVerifications.model_json_schema(),
                   "implementation": {str(p.name): file_hash(p) for p in files}})


def cached(key: str, context: FindingContext, settings: Settings) -> FindingCacheRecord | None:
    record = context.cache.get(key)
    if record and record.stage == "gaps":
        if any(g.coverage_status == "unavailable" for g in record.gaps):
            return None
        if any(d.get("retry") for d in record.audit.decisions):  # a gap dropped by a failed grading call
            return None
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(record.created_at)).total_seconds()
        if age < 0 or age >= settings.gap_coverage_ttl_s:
            return None
    return record


def merge_record(report: FindingAudit, record: FindingCacheRecord, context: FindingContext, *, reused: bool) -> None:
    context.dependencies.update(record.dependencies)
    for field_name in ("accepted", "abstained", "rejected"):
        setattr(report, field_name, getattr(report, field_name) + getattr(record.audit, field_name))
    report.decisions.extend(record.audit.decisions)
    report.reused_tasks += int(reused)
    report.generated_tasks += int(not reused)
    if trace := current_trace():
        trace.log(report.stage + "_finder", "finding task cache", "reuse" if reused else "generated",
                  result=record.audit.model_dump(), why="Full task inputs, original sources, model, prompts and schemas are bound to the cache key")
