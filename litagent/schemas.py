"""Input/output contracts between agents.

Every agent returns one of these models instead of free text, so the next agent,
the grading agent and the front end can all rely on the same fields.
For Track 02, findings carry Evidence: every claim points back to a paper and a quote.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from litagent.config import Effort

# ---------- Planner ----------


class SearchCriteria(BaseModel):
    topic: str
    year_from: int | None = None
    year_to: int | None = None
    min_citations: int | None = None  # only when the user gives a number, e.g. "at least 50 citations"
    min_citations_per_year: float | None = None
    paper_types: list[Literal["primary", "review"]] = Field(
        default_factory=list, description="Empty = user didn't say; the Planner's defaults fill it"
    )


class SearchPlan(BaseModel):
    question: str
    criteria: SearchCriteria
    queries: list[str] = Field(description="Search strings to send to the scholarly APIs")
    effort: Effort
    max_papers: int
    token_budget: int
    used_defaults: list[str] = Field(default_factory=list, description="Which criteria fell back to defaults")
    rationale: str | None = None  # one sentence from the Planner: why these criteria and queries


class PlannerResult(BaseModel):
    status: Literal["ok", "need_topic"]
    plan: SearchPlan | None = None
    message_to_user: str | None = None  # friendly prompt when status == "need_topic"


# ---------- Retriever ----------


class Paper(BaseModel):
    id: str
    title: str
    abstract: str | None = None
    year: int | None = None
    authors: list[str] = Field(default_factory=list)
    citation_count: int | None = None
    is_review: bool | None = None
    is_open_access: bool = False
    pdf_url: str | None = None
    doi: str | None = None
    source: str  # e.g. "openalex", "semantic_scholar", "arxiv"
    full_text: str | None = None  # only filled at High / Ultra effort
    # OpenAlex ids of the works this paper cites (OpenAlex `referenced_works`). None = unknown: the source
    # gives no list (Semantic Scholar, arXiv) or OpenAlex has none, so the Gap finder can't check citations.
    references: list[str] | None = None


class RetrievalSummary(BaseModel):
    """Shown to the user at Human review 1."""

    papers: list[Paper]
    summary: str
    follow_up_question: str = "Are these relevant? Any preferences on years, citations or paper type?"


# ---------- Clusterer / Connection finder / Gap finder ----------


class Evidence(BaseModel):
    paper_id: str
    quote: str  # verbatim text from the paper's abstract or full text


class ClusterLabel(BaseModel):
    """The labeller names a fixed group; it cannot change membership or invent paper ids."""

    model_config = ConfigDict(str_strip_whitespace=True)
    label: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class Cluster(BaseModel):
    id: str
    label: str
    paper_ids: list[str]
    rationale: str  # why these papers belong together


class ClusterAssessment(ClusterLabel):
    """Evidence-grounded naming of a fixed cluster, with an explicit abstention path."""

    cluster_id: str
    coherence: Literal["coherent", "mixed", "insufficient_evidence"]
    contrast: str = Field(min_length=1, description="Supported distinction from neighbors, or an explicit inability to distinguish")
    evidence: list[Evidence] = Field(default_factory=list)


class ClusterAssessmentBatch(BaseModel):
    assessments: list[ClusterAssessment]


class EvidenceReference(BaseModel):
    """An LLM selects a supplied source span; code copies the original bytes into Evidence."""

    paper_id: str
    span_id: str


class ClusterAssessmentProposal(ClusterLabel):
    cluster_id: str
    coherence: Literal["coherent", "mixed", "insufficient_evidence"]
    contrast: str = Field(min_length=1)
    evidence: list[EvidenceReference] = Field(default_factory=list)


class ClusterAssessmentProposals(BaseModel):
    assessments: list[ClusterAssessmentProposal]


class TopicProposal(ClusterLabel):
    paper_ids: list[str] = Field(min_length=1)
    evidence: list[EvidenceReference] = Field(default_factory=list)


class TopicProposals(BaseModel):
    topics: list[TopicProposal]


class QuestionRelevanceProposal(BaseModel):
    paper_id: str
    relevance: Literal["direct", "supporting", "uncertain"]
    reason: str = Field(min_length=1)
    evidence: list[EvidenceReference] = Field(default_factory=list)


class QuestionRelevanceBatch(BaseModel):
    assessments: list[QuestionRelevanceProposal]


class ClusterAlternative(BaseModel):
    cluster_id: str
    similarity: float = Field(ge=-1, le=1, allow_inf_nan=False)
    min_similarity: float = Field(ge=-1, le=1, allow_inf_nan=False)
    meets_membership_criteria: bool
    reason: str


class PaperClusterDetail(BaseModel):
    paper_id: str
    question_similarity: float = Field(ge=-1, le=1, allow_inf_nan=False)
    relevance: Literal["direct", "supporting", "uncertain"]
    reason: str
    evidence: list[Evidence] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    assigned_similarity: float | None = Field(default=None, ge=-1, le=1, allow_inf_nan=False)
    runner_up_cluster_id: str | None = None
    runner_up_similarity: float | None = Field(default=None, ge=-1, le=1, allow_inf_nan=False)
    margin: float | None = Field(default=None, ge=-2, le=2, allow_inf_nan=False)
    near_boundary: bool = False
    also_related: list[ClusterAlternative] = Field(default_factory=list)

    @model_validator(mode="after")
    def own_evidence(self):
        if any(e.paper_id != self.paper_id for e in self.evidence):
            raise ValueError("Paper relevance evidence must cite that paper")
        return self


class QuestionCluster(Cluster):
    """Extends the legacy cluster contract only for question-aware runs.

    Roles: one main cluster (the most topic-relevant group), at least one foundation cluster (classic work the
    topic builds on) and side clusters. role_reason says why the clusterer gave this cluster its role."""

    kind: Literal["main", "foundation", "side"]
    question: str = Field(min_length=1)
    paper_details: list[PaperClusterDetail]
    role_reason: str | None = None

    @model_validator(mode="after")
    def complete_details(self):
        ids = [p.paper_id for p in self.paper_details]
        if not ids or len(ids) != len(set(ids)) or sorted(ids) != sorted(self.paper_ids):
            raise ValueError("Question cluster details must cover every member exactly once")
        if any(a.cluster_id == self.id for p in self.paper_details for a in p.also_related):
            raise ValueError("An alternative must reference another cluster")
        return self


# Paper-to-paper relation types (spec D3); contradiction is deliberately absent. For the directional ones the
# edge points from the earlier work (source, paper_ids[0]) to the paper that builds on, benchmarks against or
# cites it (target, paper_ids[1]).
EdgeRelation = Literal["builds_on", "same_method_different_domain", "same_problem_different_method",
                       "benchmarks_against", "directly_cites"]
DIRECTIONAL_RELATIONS = {"builds_on", "benchmarks_against", "directly_cites"}
LegacyRelation = Literal["shared_method", "shared_task", "complementary", "contrasting_results", "explicit_extension"]


class Connection(BaseModel):
    """An edge between two papers, never between clusters (spec D1)."""

    id: str
    kind: Literal["within_cluster", "between_clusters"]
    paper_ids: list[str]  # [source, target]
    cluster_ids: list[str]
    description: str  # same text as reason_short, kept for older readers
    evidence: list[Evidence]
    reason_short: str | None = None  # one sentence a human can read: why these two papers are linked
    reason_long: str | None = None  # 2-4 sentences
    evidence_notes: list[str] = Field(default_factory=list)  # e.g. "shared method: contrastive loss", "W2 cites W1"


class CoverageSearch(BaseModel):
    query: str
    provider: str = "openalex"
    checked_at: str
    status: Literal["ok", "unavailable"]
    papers: list[Paper] = Field(default_factory=list)
    error: str | None = None


class GapCoverage(BaseModel):
    status: Literal["no_address_found_in_checked_sources", "inconclusive", "unavailable", "addressed"]
    checked_at: str
    local_papers_checked: int
    local_papers_considered: int = 0
    searches: list[CoverageSearch] = Field(default_factory=list)
    addressing_paper_ids: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    reason: str
    scope: str = "Bounded original-source excerpts and top OpenAlex results; this does not establish global novelty."


GapLabel = Literal["trivial", "known_open", "known_solved", "novel"]


class Gap(BaseModel):
    id: str
    cluster_id: str
    description: str  # the claim: "paper A shows X, paper B shows Y, no work combines them"
    between_paper_ids: list[str]
    why_it_matters: str
    evidence: list[Evidence]  # the grounds: one verbatim quote from each paper
    # Gap finder stages (docs/agents/gap_finder.md). Defaults keep older gaps and the front end valid.
    gap_type: Literal["inferred", "explicit"] = "inferred"  # explicit = stated as open by one paper's authors
    paper_a_id: str | None = None
    paper_b_id: str | None = None  # None for an explicit gap
    warrant: str | None = None  # why the grounds imply the gap
    similarity: float | None = Field(default=None, ge=-1, le=1, allow_inf_nan=False)
    citation_check: Literal["passed", "unknown"] | None = None  # unknown = a paper has no reference list
    coverage_query: str | None = None
    coverage_status: Literal["not_filled", "filled", "unavailable", "skipped"] | None = None
    coverage: GapCoverage | None = None
    label: GapLabel | None = None
    label_reason: str | None = None


class GroundedConnection(Connection):
    relation: EdgeRelation | LegacyRelation  # legacy values only appear in maps saved before spec D
    similarity: float = Field(ge=-1, le=1, allow_inf_nan=False)
    verification: Literal["source_supported"] = "source_supported"


class GroundedGap(Gap):
    cluster_ids: list[str] = Field(default_factory=list)
    scope: Literal["within_cluster", "main_side"] = "within_cluster"
    basis: Literal["author_stated", "cross_paper_hypothesis"]
    hypothesis_status: Literal["provisional"] = "provisional"
    proposed_test: str = Field(min_length=1)
    similarity: float = Field(ge=-1, le=1, allow_inf_nan=False)
    coverage: GapCoverage

    @model_validator(mode="after")
    def complete_scope(self):
        if not self.cluster_ids:
            self.cluster_ids = [self.cluster_id]
        expected = 2 if self.scope == "main_side" else 1
        if len(self.cluster_ids) != expected or len(set(self.cluster_ids)) != expected or self.cluster_id not in self.cluster_ids:
            raise ValueError("Gap scope must identify its actual one or two clusters and include the anchor")
        return self


class ReviewAgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version_token: str = Field(pattern=r"^[a-f0-9]{32}$")


class ReviewAgentScores(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_support: int = Field(ge=0, le=3)
    relevance: int = Field(ge=0, le=3)
    testability: int = Field(ge=0, le=3)


class ReviewAgentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: str
    verdict: Literal["supported", "unsupported", "uncertain"]
    scores: ReviewAgentScores
    reason: str = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)
    evidence: list[EvidenceReference] = Field(default_factory=list)


class ReviewAgentDecisions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decisions: list[ReviewAgentDecision]


class ReviewExplanationAttribution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paper_id: str
    statement_id: str = Field(description="Exact ID of the draft sentence being checked")
    assertion: str = Field(min_length=1, description="One factual assertion from the draft about this paper")
    evidence: list[EvidenceReference]
    assessment: Literal["grounded", "proposal", "scope_limit", "unsubstantiated", "contradicted"]
    explanation: str = Field(min_length=1)


class ReviewExplanationCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: str
    attributions: list[ReviewExplanationAttribution]
    issues: list[str] = Field(description="Concrete source-attribution errors; empty only if the explanation passes")


class ReviewExplanationChecks(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checks: list[ReviewExplanationCheck]


class ReviewAgentAssessment(BaseModel):
    item_id: str
    status: Literal["assessed", "needs_hypothesis", "insufficient_sources", "sample"]
    verdict: Literal["supported", "unsupported", "uncertain"] | None = None
    scores: ReviewAgentScores | None = None
    total: int | None = None
    reason: str
    limitations: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)


class ConnectionDecision(BaseModel):
    pair_id: str
    decision: Literal["supported", "abstain"]
    relation: EdgeRelation | None = None
    base_paper_id: str | None = Field(default=None, description="For builds_on, benchmarks_against and directly_cites: "
                                      "the paper that is built on, compared against or cited")
    reason_short: str = Field(default="", description="One sentence naming the concrete method, dataset, claim or citation")
    reason_long: str = Field(default="", description="2-4 sentences")
    evidence_notes: list[str] = Field(default_factory=list, description="Short facts, e.g. 'shared method: contrastive loss'")
    reason: str = Field(min_length=1)
    evidence: list[EvidenceReference] = Field(default_factory=list)


class ConnectionDecisions(BaseModel):
    decisions: list[ConnectionDecision]


class GapDraft(BaseModel):
    """Gap writer output for one candidate pair, in GAPMAP's Claim / Grounds / Warrant shape."""

    gap_id: str
    decision: Literal["write", "abstain"]
    claim: str = ""
    grounds: list[EvidenceReference] = Field(default_factory=list, description="One source span from each paper")
    warrant: str = ""
    coverage_query: str = Field(default="", description="Short search query for a paper that already does what the claim says is missing")
    reason: str = Field(min_length=1)


class GapDrafts(BaseModel):
    drafts: list[GapDraft]


class ExplicitGapDraft(BaseModel):
    paper_id: str
    sentence: str = Field(min_length=1, description="Copied verbatim from the paper's abstract")
    coverage_query: str = Field(min_length=1)


class ExplicitGapDrafts(BaseModel):
    gaps: list[ExplicitGapDraft]


class CoverageJudgement(BaseModel):
    gap_id: str
    filled: bool
    filling_paper_id: str | None = None
    evidence: list[EvidenceReference] = Field(default_factory=list, description="A span of the filling paper")
    reason: str = Field(min_length=1)


class CoverageJudgements(BaseModel):
    judgements: list[CoverageJudgement]


class GapLabelDecision(BaseModel):
    gap_id: str
    label: GapLabel
    reason: str = Field(min_length=1, description="One sentence")
    fix: str | None = Field(default=None, description="Only when the claim misstates its quotes: one concrete correction")


class GapLabelDecisions(BaseModel):
    labels: list[GapLabelDecision]


class FindingVerification(BaseModel):
    pair_id: str
    verdict: Literal["supported", "generic", "insufficient"]  # generic: true but could describe almost any pair
    reason: str = Field(min_length=1)


class FindingVerifications(BaseModel):
    verdicts: list[FindingVerification]


class FindingAudit(BaseModel):
    stage: Literal["connections", "gaps"]
    candidate_pairs: int = 0
    accepted: int = 0
    abstained: int = 0
    rejected: int = 0
    duplicate_pairs_skipped: int = 0
    reused_tasks: int = 0
    generated_tasks: int = 0
    decisions: list[dict[str, Any]] = Field(default_factory=list)


# ---------- Grading agents ----------


class Grade(BaseModel):
    stage: Literal["clusters", "connections", "gaps"]
    accuracy: int = Field(ge=0, le=3)
    appropriateness: int = Field(ge=0, le=3)
    actionability: int = Field(ge=0, le=3)
    fix: str | None = None  # one concrete fix when the grade fails
    reasoning: str = ""

    @property
    def total(self) -> int:
        return self.accuracy + self.appropriateness + self.actionability


# ---------- Human review ----------


class HumanFeedback(BaseModel):
    approved: bool
    comment: str | None = None


# ---------- Final output ----------


class TokenUsage(BaseModel):
    """LLM tokens used by one run, checked against the effort level's token budget."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    llm_calls: int = 0
    estimated_calls: int = 0  # calls where the provider reported no usage, so tokens were estimated
    budget: int | None = None

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class ClusterMove(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    paper_id: str = Field(min_length=1)
    target_cluster_id: str = Field(min_length=1)


class MoveCandidate(BaseModel):
    paper_id: str
    source_cluster_id: str
    target_cluster_id: str
    assigned_similarity: float | None
    target_similarity: float
    target_min_similarity: float
    margin: float | None
    eligible: bool
    reason: str


class MembershipChange(BaseModel):
    cluster_id: str
    before: list[str]
    after: list[str]


class FindingDependency(BaseModel):
    """Unknown dependency scope is global, so old findings cannot be reused unsafely."""

    cluster_ids: list[str] = Field(default_factory=list)
    paper_ids: list[str] = Field(default_factory=list)
    finding_ids: list[str] = Field(default_factory=list)
    global_map: bool = True


class FindingCacheRecord(BaseModel):
    stage: Literal["connections", "gaps"]
    created_at: str
    connections: list[GroundedConnection] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    dependencies: dict[str, FindingDependency] = Field(default_factory=dict)
    audit: FindingAudit


class FindingAnalysis(BaseModel):
    request_id: str
    source_run_id: str
    completed_stages: list[str] = Field(default_factory=list)
    pending_stages: list[str] = Field(default_factory=list)
    audits: list[FindingAudit] = Field(default_factory=list)
    grades: dict[str, Grade] = Field(default_factory=dict)


class RegenerationPlan(BaseModel):
    preview_id: str
    sample_mode: bool = False
    source_run_id: str
    source_version_token: str
    root_run_id: str
    proposed_run_id: str
    revision: int
    moves: list[ClusterMove]
    changes: list[MembershipChange]
    relabel_cluster_ids: list[str]
    reused_label_cluster_ids: list[str]
    invalidated_connection_ids: list[str] = Field(default_factory=list)
    invalidated_gap_ids: list[str] = Field(default_factory=list)
    applicable: bool
    errors: list[str] = Field(default_factory=list)


class RegenerationSummary(BaseModel):
    preview_id: str
    moved_paper_ids: list[str]
    relabelled_cluster_ids: list[str]
    reused_label_cluster_ids: list[str]
    invalidated_connection_ids: list[str] = Field(default_factory=list)
    invalidated_gap_ids: list[str] = Field(default_factory=list)
    pending_stages: list[str] = Field(default_factory=list)
    reused_embeddings: bool = True
    reused_similarity_matrix: bool = True


class RunResult(BaseModel):
    run_id: str
    # partial = time limit or token budget hit; no_results = the searches ran but found no papers
    status: Literal["done", "need_topic", "no_results", "max_replans_reached", "partial"]
    message_to_user: str | None = None
    plan: SearchPlan | None = None
    papers: list[Paper] = Field(default_factory=list)
    clusters: list[QuestionCluster | Cluster] = Field(default_factory=list)
    connections: list[GroundedConnection | Connection] = Field(default_factory=list)
    gaps: list[GroundedGap | Gap] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)  # e.g. a stage that never passed grading
    paper_map: dict[str, Any] | None = None  # Meterless world model graph (nodes + edges) for the front end
    usage: TokenUsage | None = None


class ClusterMapResult(BaseModel):
    run_id: str
    stage: Literal["clusters", "findings"] = "clusters"
    status: Literal["done", "partial"] = "done"
    question: str
    sample_mode: bool = False
    map_mode: Literal["question", "topic"] = "question"
    embedding_profile: str = "semcse"
    use_full_text: bool = False
    side_linkage: Literal["complete", "average"] = "complete"
    side_similarity_threshold: float = 0.7
    similarity_settings: dict[str, Any] = Field(default_factory=dict)
    revision: int = 0
    root_run_id: str | None = None
    parent_run_id: str | None = None
    version_token: str | None = None
    regeneration: RegenerationSummary | None = None
    connections: list[GroundedConnection | Connection] = Field(default_factory=list)
    gaps: list[GroundedGap | Gap] = Field(default_factory=list)
    analysis: FindingAnalysis | None = None
    main_similarity_threshold: float
    main_cluster_id: str | None = None
    clusters: list[QuestionCluster | Cluster] = Field(default_factory=list)
    grade: Grade | None = None
    warnings: list[str] = Field(default_factory=list)
    paper_map: dict[str, Any] | None = None
    usage: TokenUsage | None = None
