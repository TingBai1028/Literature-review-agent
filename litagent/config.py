"""Settings, effort levels and default search criteria.

Change numbers here, not inside the agents, so the whole team tunes one place.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class Effort(str, Enum):
    """Fast and Pro are the two modes the UI offers (spec F, 26 Oct). The four older levels stay accepted for
    saved maps, scripts and the example inputs; thoroughness order: normal <= fast <= pro <= ultra."""

    FAST = "fast"
    PRO = "pro"
    NORMAL = "normal"
    MEDIUM = "medium"
    HIGH = "high"
    ULTRA = "ultra"


@dataclass(frozen=True)
class EffortProfile:
    max_papers: int  # papers shown on the map
    use_full_text: bool  # False = metadata only, True = download and read PDFs
    token_budget: int  # whole run, retries and redos included (see measured usage below)
    num_queries: int  # search queries the Planner writes; more papers -> more phrasings
    # Fast/Pro: papers to retrieve (a soft target). Everything beyond max_papers becomes the ranked backup pool
    # that "refresh" swaps in. None = retrieve max_papers and keep no pool (the older levels).
    retrieval_target: int | None = None


# Caps from measured real 30-paper /runs (26 Oct, docs/evaluation.md): planning + summary ~6k, each
# clustering attempt ~37k (question relevance ~20k, labels ~10k, whole-map grade ~15k), connections
# ~35k, gaps ~25k, each finding grade ~13k; with one cluster and one finding redo about 210k. The old
# 50k Normal budget stopped every real run inside clustering, and 150k inside the connection redo.
# Relevance batches and grader input grow with the paper count, so the caps scale with it.
EFFORT_PROFILES: dict[Effort, EffortProfile] = {
    # Spec F defaults (open questions, 26 Oct): Fast retrieves at least 300, Pro about 1,000; both show ~50.
    # LLM work scales with the shown papers, not the pool, so budgets sit between the old levels.
    Effort.FAST: EffortProfile(max_papers=50, use_full_text=False, token_budget=350_000, num_queries=3, retrieval_target=300),
    Effort.PRO: EffortProfile(max_papers=50, use_full_text=True, token_budget=800_000, num_queries=5, retrieval_target=1000),
    Effort.NORMAL: EffortProfile(max_papers=30, use_full_text=False, token_budget=250_000, num_queries=2),
    Effort.MEDIUM: EffortProfile(max_papers=60, use_full_text=False, token_budget=450_000, num_queries=3),
    Effort.HIGH: EffortProfile(max_papers=100, use_full_text=True, token_budget=700_000, num_queries=4),
    Effort.ULTRA: EffortProfile(max_papers=150, use_full_text=True, token_budget=1_000_000, num_queries=4),
}


# Meterless World Model: authors recorded per paper (consortium papers can list hundreds)
WORLD_MODEL_MAX_AUTHORS = 10

# CPU encoder, pinned so threshold comparisons use the same model on every machine.
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
EMBEDDING_PROFILES = {
    "minilm": {"model": EMBEDDING_MODEL, "revision": EMBEDDING_REVISION, "pooling": "mean",
               "chunk_tokens": 224, "batch_size": 16},
    "semcse": {"model": "CLAUSE-Bielefeld/SemCSE_cosine",
               "revision": "abc74650cfd087c38d27c480778ac41907a08367", "pooling": "cls",
               "chunk_tokens": 448, "batch_size": 4},
}
EMBEDDING_DOWNLOAD_TIMEOUT_S = 60
EMBEDDING_METADATA_TIMEOUT_S = 15
CLUSTER_MAX_PAPER_FRACTION = 0.4
CLUSTER_MAX_SINGLETON_FRACTION = 0.5
CLUSTER_THRESHOLD_SWEEP = (0.5, 0.6, 0.7, 0.8, 0.9)
SIMILARITY_HYBRID_DENSE_WEIGHT = 0.85  # optional ablation, not the production default


@dataclass(frozen=True)
class DefaultCriteria:
    """Used by the Planner when the user doesn't say otherwise (team decision, 22 Oct)."""

    # No default start year (26 Oct, replaces the 22 Oct 5-year window): it dropped the classic papers
    # theoretical questions depend on. Set a number to restore a default window.
    years_back: int | None = None
    paper_types: tuple[str, ...] = ("primary", "review")
    # Team decision (24 Oct): no default minimum. Citations only filter when the user gives a number;
    # otherwise the Retriever ranks by citations per year so recent papers aren't penalised.
    min_citations_per_year: float | None = None

    @property
    def year_from(self) -> int | None:
        return None if self.years_back is None else date.today().year - self.years_back


# Nightshift model for every agent. Must be an NVIDIA Nemotron model, set explicitly
# (no automatic routing, which could pick a non-NVIDIA model).
# Nemotron 3 Ultra (550B total / 55B active MoE) through Nightshift's NVIDIA provider (the route the
# NVIDIA award needs). Tested 24 Oct through Nightshift: Ultra answers (0.8 s for a tiny call);
# Nemotron 3 Super and Llama 3.1 Nemotron Ultra return 404 for our NVIDIA account, Llama 3.3 Nemotron
# Super is retired (410), and 3.5 Super VL is excluded by Nightshift for unreliable responses.
# Fallback that also works: "nvidia/nemotron-3.5-lightning-30b-a3b" (slower here, reasons at length).
# llm.py strips <think> blocks before parsing JSON in case reasoning is returned.
NIGHTSHIFT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes"}


@dataclass
class Settings:
    # Sample mode: the whole pipeline runs on data/sample/ with no Zetaris, Nightshift or network
    sample_mode: bool = field(default_factory=lambda: _env_bool("SAMPLE_MODE"))

    # LLM (Meterless Nightshift, OpenAI-compatible)
    llm_model: str = NIGHTSHIFT_MODEL
    # Per model request (rules: 30-90 s). 60 s cut off two of three real evaluation topics: Nightshift
    # latency spikes made a ~2k-token request take 62-68 s where it usually takes ~10 s (26 Oct).
    llm_timeout_s: float = 90.0
    # Independent model calls sent at once (litagent/parallel.py). Nightshift served 8 concurrent requests without
    # errors (26 Oct); 4 leaves headroom for latency spikes. 1 = one after another.
    llm_concurrency: int = field(default_factory=lambda: int(os.getenv("LLM_CONCURRENCY", "4")))

    # Zetaris SQL requests (rules: 30-60 s)
    zetaris_timeout_s: float = 45.0

    # Whole run: stop between stages and return a partial result after this many seconds
    run_timeout_s: float = field(default_factory=lambda: float(os.getenv("RUN_TIMEOUT_S", "600")))
    # Live progress events (GET /runs/{run_id}/events): how long to wait for a subscribed run to start,
    # and how long past run_timeout_s to keep streaming before giving up
    event_stream_wait_s: float = 60.0
    event_stream_grace_s: float = 300.0

    # Retriever ranking: share of relevance vs citations per year (team decision, 24 Oct). It only orders the
    # papers already chosen by relevance; citations never bring an off-topic paper into the list (26 Oct).
    # Fast/Pro rank the whole pool with w = this weight (spec F2): w * relevance + (1 - w) * log-scaled citations.
    rank_relevance_weight: float = 0.7
    # Relevance floor: question-paper cosine with the clustering embedding model, on the same scale as
    # main_similarity_threshold. On a 494-paper average-reward-MDP pool, papers above 0.5 were MDP theory and
    # those below it generic deep RL; title + 600 abstract characters kept the ranking (Spearman 0.97 vs the
    # full abstract) in 42 s instead of 101 s on CPU.
    retrieval_similarity_min: float = 0.5
    retrieval_relevance_text_chars: int = 600
    # Scholarly APIs each query runs against; a failing source is logged and skipped. Semantic Scholar's
    # shared keyless rate limit answered 429 on every live check, so it is a default only with a key.
    retrieval_sources: tuple[str, ...] = field(default_factory=lambda: tuple(s.strip() for s in os.getenv(
        "RETRIEVAL_SOURCES", "openalex,semantic_scholar,arxiv" if os.getenv("SEMANTIC_SCHOLAR_API_KEY") else "openalex,arxiv",
    ).split(",") if s.strip()))

    # Full text (High / Ultra): open-access PDFs only, fetched concurrently within one overall deadline
    full_text_timeout_s: float = 20.0  # per PDF request
    full_text_total_timeout_s: float = 120.0  # all downloads together; the rest fall back to abstracts
    full_text_workers: int = 6
    full_text_max_bytes: int = 15_000_000
    full_text_max_pages: int = 30
    full_text_min_chars: int = 2000  # less extractable text than this is treated as a scanned PDF
    full_text_max_chars: int = 200_000

    # Clustering
    cluster_map_mode: str = "question"  # question-aware main/side map when a question is provided; topic retains legacy behavior
    main_similarity_threshold: float = 0.5  # candidate gate, not a calibrated relevance probability
    # Cluster roles (docs/agents/clusterer.md): one main cluster of 5-10 papers, at least one foundation
    # cluster of classic work (3-10 papers), side clusters of at least 3 papers (team defaults, 26 Oct).
    main_cluster_min_size: int = 5
    main_cluster_max_size: int = 10
    main_relevance_weight: float = 0.2  # weight of the LLM relevance check next to question cosine
    foundation_min_size: int = 3
    foundation_max_size: int = 10
    side_min_size: int = 3
    main_relevance_batch_size: int = 10
    main_relevance_text_chars: int = 1400
    side_linkage: str = "complete"  # average is an explicit comparison option
    side_similarity_threshold: float = 0.7
    related_similarity_threshold: float = 0.5
    related_cluster_limit: int = 2
    related_boundary_margin: float = 0.05
    paper_keyword_limit: int = 6
    regeneration_max_moves: int = 20
    regeneration_candidate_limit: int = 40
    regeneration_max_revisions: int = 30
    regeneration_score_tolerance: float = 1e-5
    cluster_similarity_threshold: float = 0.7  # fixed mode / fallback; hybrid scores are not probabilities
    cluster_threshold_mode: str = "fixed"  # adaptive is an experimental, unsupervised coarse-topic cut
    cluster_threshold_candidates: tuple[float, ...] = (0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8)
    cluster_dense_weight: float = 1.0  # lexical fusion is opt-in: it did not consistently improve clustering
    cluster_lexical_title_weight: float = 0.35
    cluster_lexical_max_df: float = 0.95
    cluster_lexical_max_features: int = 20_000
    cluster_lexical_ngram_range: tuple[int, int] = (1, 2)
    cluster_redo_threshold_step: float = 0.05
    cluster_label_text_chars: int = 2000
    cluster_label_max_papers: int = 8
    cluster_label_strategy: str = "contrastive"  # independent retained for controlled comparisons
    cluster_label_batch_size: int = 4
    cluster_label_neighbors: int = 2
    cluster_neighbor_text_chars: int = 600
    cluster_label_validation_retries: int = 1
    cluster_evidence_min_chars: int = 20
    cluster_evidence_span_chars: int = 400
    cluster_grouping_strategy: str = "complete"  # semantic is an evidence-grounded, constrained candidate
    cluster_semantic_text_chars: int = 1400
    cluster_semantic_neighbor_limit: int = 6
    cluster_representative_relevance_weight: float = 0.7  # MMR: centrality versus redundant examples
    embedding_profile: str = field(default_factory=lambda: os.getenv("EMBEDDING_PROFILE", "semcse"))
    embedding_model_dir: str | None = field(default_factory=lambda: os.getenv("EMBEDDING_MODEL_DIR"))
    embedding_batch_size: int = 16
    embedding_chunk_tokens: int | None = None  # profile default, bounded by the model's token window
    embedding_max_chunks_per_paper: int = 16

    # Evidence-grounded scientific findings; pair caps bound model cost independently of n².
    finding_source_chars: int = 1800
    finding_span_chars: int = 400
    finding_min_quote_chars: int = 20
    finding_validation_retries: int = 1
    finding_grader_source_chars: int = 1400
    connection_similarity_min: float = 0.5
    connection_within_pairs_per_cluster: int = 2
    connection_max_within_pairs: int = 4
    connection_max_between_pairs: int = 4
    connection_max_pairs_per_paper: int = 2
    # Cluster cards (spec H3): papers per card summary and characters read from each
    cluster_card_papers: int = 5
    cluster_card_text_chars: int = 600
    # Gap finder escalation (spec H5): when a side cluster holds kept gaps, read full text for its top papers
    gap_escalation_enabled: bool = True
    gap_escalation_max_clusters: int = 1
    gap_escalation_papers: int = 3
    # Gap finder (docs/agents/gap_finder.md). Pairs within one cluster whose cosine is in this band: below it the
    # papers are unrelated, above it near-duplicates. 0.5-0.8 is a draft range, not yet tuned for our encoder.
    gap_similarity_min: float = 0.5
    gap_similarity_max: float = 0.8
    gap_max_per_cluster: int = 5  # gaps kept per cluster after grading
    gap_llm_batch_size: int = 5  # candidates or gaps per writer, coverage and grading request
    gap_candidate_multiplier: int = 3  # candidates per cluster sent to the LLM = gap_max_per_cluster x this
    gap_coverage_check: bool = field(default_factory=lambda: _env_bool("GAP_COVERAGE_CHECK", "true"))
    gap_explicit_enabled: bool = field(default_factory=lambda: _env_bool("GAP_EXPLICIT_ENABLED"))
    gap_coverage_results: int = 5  # top search results, excluding the gap's own papers, the LLM checks
    gap_coverage_hits_per_query: int = 7  # fetched per source, so 5 remain after removing papers A and B
    gap_coverage_source_chars: int = 1000
    gap_coverage_timeout_s: float = 20.0
    gap_coverage_ttl_s: float = 86400

    # Independent per-claim AI review; separate from human annotations and finding production.
    review_agent_source_chars: int = 6000
    review_agent_max_items: int = 24
    review_agent_token_budget: int = 30000
    review_agent_timeout_s: float = 180.0
    review_agent_metric_terms: tuple[str, ...] = ("spBLEU", "BLEU", "COMET", "chrF", "ROUGE", "METEOR", "BERTScore")

    # Offline quality review: targeted diagnostics, not a population accuracy estimate.
    cluster_review_pairs_per_stratum: int = 8

    # Grading agents: rubric is 3 criteria x 0-3 points = 9 points (Day 4 workshop)
    grade_pass_mark: int = 7
    max_redo_per_stage: int = 1  # one fix, then revise once

    # Outer loop: how many times human feedback can send the run back to the Planner
    max_replans: int = 3

    defaults: DefaultCriteria = field(default_factory=DefaultCriteria)

    logs_dir: str = "logs"

    @property
    def embedding_directory(self) -> str:
        if self.embedding_profile not in EMBEDDING_PROFILES:
            raise ValueError(f"Unknown embedding profile: {self.embedding_profile}")
        suffix = "" if self.embedding_profile == "minilm" else f"-{self.embedding_profile}"
        return self.embedding_model_dir or str(
            Path(__file__).resolve().parents[1] / f"data/cache/embedding-model{suffix}")
