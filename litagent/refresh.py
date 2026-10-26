"""Refresh (spec F5): swap the side-cluster papers for the next-best papers of the backup pool.

Builds on the regeneration machinery (immutable versions, version lock, head, rollback): the result is a new map
version that reuses the stored vectors, keeps the main and foundation clusters unchanged (members, labels, role
reasons), embeds only the incoming papers, regroups and relabels the side clusters, and puts the swapped-out
papers back at the end of the ranked pool. Findings that touch a side paper are dropped and the finding stages are
marked pending. No pipeline stage before clustering is re-run.
"""

from __future__ import annotations

import time
import uuid

import numpy as np

from litagent.agents import grader
from litagent.agents.clusterer import _text_for
from litagent.cluster_cards import build_cards
from litagent.cluster_roles import side_groups
from litagent.cluster_state import (ClusteringArtifacts, VersionError, effective_settings, head, load_version, path_for,
                                    save_version, set_head, version_lock)
from litagent.config import EFFORT_PROFILES, Settings
from litagent.integrations.embeddings import embed_documents
from litagent.integrations.llm import LLMError, TokenBudgetExceeded, TokenMeter
from litagent.integrations.meterless import ResearchWorld
from litagent.question_clusters import attach_alternatives, cluster_id, label_side_groups, paper_keywords
from litagent.sample_data import sample_relevance, sample_similarity
from litagent.schemas import ClusterMapResult, FindingAnalysis, PaperClusterDetail, QuestionCluster
from litagent.similarity import paper_similarity
from litagent.trace import Trace, new_run_id

SWAPPED_IN = "Swapped in from the backup pool by refresh; side papers are not checked against the question."


def refresh_map(run_id: str, expected_version_token: str, settings: Settings,
                child_run_id: str | None = None) -> ClusterMapResult:
    source, state, arrays = load_version(run_id, settings)
    with version_lock(settings, source.root_run_id):
        if source.version_token != expected_version_token:
            raise VersionError("Source version token changed; refresh the map")
        if head(source.root_run_id, settings)["run_id"] != run_id:
            raise VersionError("Only the active version can be refreshed; activate it first")
        if not state.backup_papers:
            raise VersionError("This map has no backup pool; Fast and Pro maps keep one", 422)
        if not any(c.kind == "side" for c in source.clusters):
            raise VersionError("This map has no side clusters to refresh; main and foundation stay fixed", 422)
        child_id = child_run_id or new_run_id()
        if any(path_for(settings, prefix, child_id, suffix).exists() for prefix, suffix in (
                ("cluster-map", "json"), ("cluster-state", "json"), ("trace", "jsonl"))):
            raise VersionError("Run ID already exists; choose a new ID for the refresh")
        with version_lock(settings, child_id):
            return _refresh(source, state, arrays, effective_settings(state, settings), child_id)


def _refresh(source, state, arrays, cfg: Settings, child_id: str) -> ClusterMapResult:
    started = time.monotonic()
    with Trace(cfg.logs_dir, child_id) as trace, TokenMeter(EFFORT_PROFILES[state.effort].token_budget) as meter:
        fixed = [c for c in source.clusters if c.kind != "side"]
        fixed_ids = {pid for c in fixed for pid in c.paper_ids}
        # Every side paper is swapped when the pool is large enough; otherwise the least question-relevant side
        # papers go first, so the map keeps its size.
        side = sorted((d for c in source.clusters if c.kind == "side" for d in c.paper_details),
                      key=lambda d: (d.question_similarity, d.paper_id))
        outgoing = [d.paper_id for d in side[:min(len(side), len(state.backup_papers))]]
        staying = {d.paper_id for d in side} - set(outgoing)
        incoming = state.backup_papers[:len(outgoing)]
        by_id = {p.id: p for p in state.papers}
        pool = state.backup_papers[len(incoming):] + [by_id[pid] for pid in outgoing]
        old_details = {d.paper_id: d for d in side}
        trace.log("orchestrator", "refresh", f"swap {len(outgoing)} side papers", phase="start",
                  message=f"Refresh: swapping {len(outgoing)} side papers for the next {len(incoming)} from the backup pool; "
                          "main and foundation stay", result={"source_run_id": source.run_id})
        try:
            kept = [p for p in state.papers if p.id in fixed_ids or p.id in staying]
            papers = kept + list(incoming)
            index = {p.id: i for i, p in enumerate(state.papers)}
            kept_vectors = arrays.paper_vectors[[index[p.id] for p in kept]]
            question = arrays.question_vector
            if cfg.sample_mode:
                relevance = sample_relevance(papers, source.question)[len(kept):]
                new_vectors = np.column_stack([relevance, np.sqrt(np.clip(1 - relevance ** 2, 0, 1))])
                vectors = np.vstack([kept_vectors, new_vectors])
                similarity = sample_similarity(papers)
                if similarity is None:
                    similarity = np.ones((len(papers), len(papers)))
            else:
                new_vectors = np.asarray(embed_documents([_text_for(p, source.use_full_text) for p in incoming], cfg), dtype=float)
                vectors = np.vstack([kept_vectors, new_vectors])
                similarity = paper_similarity(papers, vectors, cfg).combined
            unit = lambda v: v / np.linalg.norm(v, axis=-1, keepdims=True)
            scores = np.clip(unit(new_vectors) @ unit(question), -1, 1)
            keywords = paper_keywords(list(incoming), cfg.paper_keyword_limit)
            details = {p.id: PaperClusterDetail(paper_id=p.id, question_similarity=float(s), relevance="uncertain",
                                                reason=SWAPPED_IN, keywords=keywords[p.id]) for p, s in zip(incoming, scores)}
            details.update({pid: old_details[pid].model_copy(deep=True) for pid in staying})
            decisions = []
            side_positions = [i for i, p in enumerate(papers) if p.id not in fixed_ids]
            groups = side_groups(papers, similarity, side_positions, cfg, decisions)
            ids = [cluster_id([papers[i].id for i in g]) for g in groups]
            texts = [p.title for p in papers] if cfg.sample_mode else [_text_for(p, source.use_full_text) for p in papers]
            labels = label_side_groups(papers, texts, groups, similarity, ids, cfg,
                                       deadline=started + cfg.run_timeout_s)
            side_reason = (f"Side: papers outside main and foundation after a refresh from the backup pool, grouped by "
                           f"content similarity ({cfg.side_linkage} linkage at {cfg.side_similarity_threshold}).")
            sides = []
            for cid, group in zip(ids, groups):
                label = labels[cid]
                if cfg.sample_mode:
                    label = label.model_copy(update={"label": f"Sample side: {papers[group[0]].title}"})
                sides.append(QuestionCluster(id=cid, kind="side", question=source.question, label=label.label,
                    rationale=label.rationale, role_reason=side_reason, paper_ids=[papers[i].id for i in group],
                    paper_details=[details[papers[i].id] for i in group]))
            clusters = attach_alternatives([c.model_copy(deep=True) for c in fixed] + sides, papers, similarity, cfg)
            keep = lambda ids: not set(ids) & set(outgoing)
            child = source.model_copy(deep=True, update={
                "run_id": child_id, "parent_run_id": source.run_id, "revision": source.revision + 1,
                "version_token": uuid.uuid4().hex, "clusters": clusters, "status": "done", "grade": None,
                "paper_map": None, "usage": None, "regeneration": None, "backup_pool_size": len(pool),
                "refresh": {"swapped_in": [p.id for p in incoming], "swapped_out": outgoing, "side_decisions": decisions},
                "connections": [c for c in source.connections if keep(c.paper_ids)],
                "gaps": [g for g in source.gaps if keep(g.between_paper_ids)],
                "analysis": FindingAnalysis(request_id=uuid.uuid4().hex, source_run_id=source.run_id,
                                            pending_stages=["connections", "gaps"]) if source.analysis else None,
                "warnings": [w for w in source.warnings if w.startswith("Sample mode:")]})
            trace.log("clusterer", "regroup side papers", f"{len(sides)} side clusters", phase="partial_result",
                      message=f"Refresh: {len(incoming)} new side papers in {len(sides)} clusters",
                      payload={"clusters": [{"id": c.id, "kind": c.kind, "label": c.label, "paper_ids": c.paper_ids}
                                            for c in sides], "swapped_out": outgoing})
            world = ResearchWorld(child_id, cfg.logs_dir)
            world.start_attempt(1, child.question)
            world.add_papers(papers)
            world.write_clusters(child.clusters)
            world.write_connections(child.connections)
            world.write_gaps(child.gaps)
            try:
                child.grade = grader.grade("clusters", child.clusters, papers, cfg)
                world.record_grade("clusters", child.grade)
                if not grader.passed(child.grade, cfg):
                    child.warnings.append("Cluster map did not pass grading; retained for review without automatic regeneration.")
            except (TokenBudgetExceeded, LLMError) as error:
                child.warnings.append(f"Refreshed map was not graded: {error}")
            child.cluster_cards = build_cards(papers, child.clusters, child.question, cfg)  # side cards changed (H3)
            child.paper_map, child.usage = world.to_graph_json(), meter.usage
            kept_findings = {f.id for f in [*child.connections, *child.gaps]}
            save_version(child, papers, state.effort, ClusteringArtifacts(paper_vectors=vectors, question_vector=question,
                         similarity=similarity), cfg, backup_papers=pool,
                         dependencies={k: v for k, v in state.finding_dependencies.items() if k in kept_findings})
            set_head(child, cfg)
        except Exception as error:
            trace.error("orchestrator", "refresh", error, next_step="keep source version active", terminal=True)
            raise
        trace.log("orchestrator", "finish refresh", child.status, phase="done", terminal=True,
                  message=f"Refreshed map saved: {len(incoming)} papers swapped in, {len(pool)} left in the pool")
        return child
