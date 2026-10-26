"""A noninteractive, single-pass clustering checkpoint independent of later TODO agents."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from litagent.agents import clusterer, grader
from litagent.cluster_audit import partition_indices
from litagent.cluster_cards import build_cards, read_role_full_text
from litagent.cluster_state import ClusteringArtifacts, VersionError, path_for, save_version, set_head, version_lock
from litagent.config import EFFORT_PROFILES, Effort, Settings
from litagent.integrations.llm import TokenBudgetExceeded, TokenMeter
from litagent.integrations.meterless import ResearchWorld
from litagent.schemas import ClusterMapResult, Paper, QuestionCluster
from litagent.trace import Trace, new_run_id


class _PreviewTimeLimit(Exception):
    pass


def run_cluster_map(papers: list[Paper], question: str, effort: Effort, settings: Settings,
                    run_id: str | None = None, backup_papers: list[Paper] = ()) -> ClusterMapResult:
    question = question.strip()
    run_id = run_id or new_run_id()
    with version_lock(settings, run_id):
        if any(path_for(settings, prefix, run_id, suffix).exists() for prefix, suffix in (
                ("cluster-map", "json"), ("cluster-state", "json"), ("world", "json"), ("trace", "jsonl"))):
            raise VersionError("Run ID already exists; create a new immutable version")
        return _run_cluster_map(papers, question, effort, settings, run_id, list(backup_papers))


def _run_cluster_map(papers: list[Paper], question: str, effort: Effort, settings: Settings,
                     run_id: str, backup_papers: list[Paper]) -> ClusterMapResult:
    if not question.strip() or not papers or len({p.id for p in papers}) != len(papers):
        raise ValueError("Clustering requires a question and unique paper IDs")
    profile = EFFORT_PROFILES[effort]
    if len(papers) > profile.max_papers:
        raise ValueError(f"{effort.value} permits at most {profile.max_papers} papers")
    started = time.monotonic()
    with Trace(settings.logs_dir, run_id) as trace, TokenMeter(profile.token_budget) as meter:
        world = ResearchWorld(trace.run_id, settings.logs_dir)
        world.start_attempt(1, question)
        world.add_papers(papers)
        result = ClusterMapResult(run_id=trace.run_id, question=question,
                                  main_similarity_threshold=settings.main_similarity_threshold,
                                  sample_mode=settings.sample_mode, map_mode=settings.cluster_map_mode,
                                  embedding_profile=settings.embedding_profile, use_full_text=profile.use_full_text,
                                  side_linkage=settings.side_linkage, side_similarity_threshold=settings.side_similarity_threshold,
                                  similarity_settings={k: getattr(settings, k) for k in (
                                      "cluster_dense_weight", "cluster_lexical_title_weight", "cluster_lexical_max_df",
                                      "cluster_lexical_max_features", "cluster_lexical_ngram_range")})
        result.similarity_settings["cluster_lexical_ngram_range"] = list(settings.cluster_lexical_ngram_range)
        artifacts = ClusteringArtifacts()
        try:
            if time.monotonic() - started > settings.run_timeout_s:
                raise _PreviewTimeLimit
            trace.log("clusterer", "start", "cluster papers", phase="start",
                      message=f"Clusterer: grouping {len(papers)} papers and choosing the main cluster")
            result.clusters = clusterer.cluster(papers, effort, settings, question=question, artifacts=artifacts,
                                                deadline=started + settings.run_timeout_s)
            partition_indices(papers, result.clusters)
            mains = [c for c in result.clusters if isinstance(c, QuestionCluster) and c.kind == "main"]
            if len(mains) > 1 or (settings.cluster_map_mode == "question" and not mains):
                raise ValueError("A question map must have exactly one main cluster")
            result.main_cluster_id = mains[0].id if mains else None
            world.write_clusters(result.clusters)
            if profile.use_full_text:
                papers = read_role_full_text(papers, result.clusters, settings)
            if settings.cluster_map_mode == "question":
                result.cluster_cards = build_cards(papers, result.clusters, question, settings)
            trace.log("clusterer", "clusters", f"{len(result.clusters)} clusters", phase="done",
                      message=f"Clusterer: {len(result.clusters)} clusters ready",
                      payload={"clusters": [{"id": c.id, "kind": getattr(c, "kind", None), "label": c.label,
                                             "paper_ids": c.paper_ids} for c in result.clusters]})
            if settings.sample_mode:
                result.warnings.append("Sample mode: TF-IDF relevance, stored similarity and placeholder labels; no model calls.")
            if time.monotonic() - started > settings.run_timeout_s:
                raise _PreviewTimeLimit
            result.grade = grader.grade("clusters", result.clusters, papers, settings)
            world.record_grade("clusters", result.grade)
            ok = grader.passed(result.grade, settings)
            trace.log("grader", "grade question map", f"{result.grade.total}/9 {'pass' if ok else 'fail'}",
                      result=result.grade, why=result.grade.fix or result.grade.reasoning)
            if not ok:
                result.warnings.append("Cluster map did not pass grading; retained for review without automatic regeneration.")
        except (TokenBudgetExceeded, _PreviewTimeLimit) as error:
            result.status = "partial"
            reason = str(error) if isinstance(error, TokenBudgetExceeded) else "Cluster-preview time limit reached"
            result.warnings.append(reason)
            trace.log("clusterer", "preview limit", "partial", why=reason)
        except Exception as error:
            trace.error("clusterer", "cluster preview", error, next_step="return error", terminal=True)
            raise
        result.paper_map = world.to_graph_json()
        result.usage = meter.usage
        if (result.clusters and all(isinstance(c, QuestionCluster) for c in result.clusters)
                and artifacts.similarity is not None):
            result.backup_pool_size = len(backup_papers)
            save_version(result, papers, effort, artifacts, settings, backup_papers=backup_papers)
            set_head(result, settings)
            _finish(trace, result)
            return result
        path = Path(settings.logs_dir) / f"cluster-map-{trace.run_id}.json"
        temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
        temporary.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
        _finish(trace, result)
        return result


def _finish(trace, result: ClusterMapResult) -> None:
    """The run's terminal event, written after the map is saved so a client can load it."""
    trace.log("orchestrator", "finish cluster map", result.status, phase="done", terminal=True,
              message=f"Cluster map saved ({result.status}): {len(result.clusters)} clusters")
