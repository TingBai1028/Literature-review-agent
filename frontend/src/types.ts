export interface Evidence {
  paper_id: string;
  quote: string;
}
export interface Paper {
  id: string;
  title: string;
  source: string;
  year?: number | null;
  abstract?: string | null;
  full_text?: string | null;
  authors?: string[];
  doi?: string | null;
  citation_count?: number | null;
}
export interface Alternative {
  cluster_id: string;
  similarity: number;
  min_similarity: number;
  meets_membership_criteria: boolean;
  reason: string;
}
export interface Detail {
  paper_id: string;
  question_similarity: number;
  relevance: string;
  reason: string;
  evidence: Evidence[];
  keywords: string[];
  assigned_similarity?: number | null;
  also_related: Alternative[];
}
export interface Cluster {
  id: string;
  label: string;
  kind?: "main" | "foundation" | "side";
  paper_ids: string[];
  rationale: string;
  role_reason?: string | null;
  paper_details?: Detail[];
}
export interface ClusterCard {
  cluster_id: string;
  role: "main" | "foundation" | "side";
  label: string;
  summary: string;
  year_range?: [number, number] | null;
  citations?: { median?: number; max?: number };
  keywords: string[];
  analysis_depth: "full_pdf" | "metadata";
  papers_with_full_text?: number;
}
export interface Connection {
  id: string;
  kind: string;
  paper_ids: string[]; // [source, target]
  cluster_ids: string[];
  description: string;
  evidence: Evidence[];
  relation?: string;
  similarity?: number;
  reason_short?: string | null;
  reason_long?: string | null;
  evidence_notes?: string[];
}
export interface Gap {
  id: string;
  cluster_id: string;
  cluster_ids?: string[];
  scope?: string;
  between_paper_ids: string[];
  description: string;
  why_it_matters: string;
  evidence: Evidence[];
  proposed_test?: string;
  hypothesis_status?: string;
  gap_type?: "inferred" | "explicit";
  paper_a_id?: string | null;
  paper_b_id?: string | null;
  warrant?: string | null;
  similarity?: number | null;
  citation_check?: "passed" | "unknown" | null;
  coverage_query?: string | null;
  coverage_status?: "not_filled" | "filled" | "unavailable" | "skipped" | null;
  label?: "trivial" | "known_open" | "known_solved" | "novel" | null;
  label_reason?: string | null;
  coverage?: {
    status: string;
    reason: string;
    scope: string;
    searches: { query: string; status: string; papers: Paper[] }[];
  } | null;
}
export interface Grade {
  accuracy: number;
  appropriateness: number;
  actionability: number;
  reasoning: string;
}
export interface MapResult {
  run_id: string;
  root_run_id: string;
  parent_run_id: string | null;
  revision: number;
  version_token: string;
  status: "done" | "partial";
  question: string;
  sample_mode: boolean;
  stage: string;
  clusters: Cluster[];
  connections: Connection[];
  gaps: Gap[];
  warnings: string[];
  grade?: Grade | null;
  backup_pool_size?: number;
  cluster_cards?: ClusterCard[];
  refresh?: { swapped_in: string[]; swapped_out: string[] } | null;
  analysis?: {
    completed_stages?: string[];
    pending_stages: string[];
    grades: Record<string, Grade>;
  } | null;
}
export interface CatalogItem {
  run_id: string;
  root_run_id: string;
  question: string;
  status: string;
  stage: string;
  revision: number;
  active: boolean;
  sample_mode: boolean;
  paper_count: number;
}
export interface Head {
  root_run_id: string;
  run_id: string;
  version_token: string;
}
export interface Versions {
  root_run_id: string;
  active_head: Head;
  versions: {
    run_id: string;
    parent_run_id: string | null;
    revision: number;
    status: string;
    version_token: string;
  }[];
}
export interface Candidate {
  paper_id: string;
  source_cluster_id: string;
  target_cluster_id: string;
  eligible: boolean;
  target_similarity: number;
  target_min_similarity: number;
  reason: string;
}
export interface Move {
  paper_id: string;
  target_cluster_id: string;
}
export interface Plan {
  preview_id: string;
  applicable: boolean;
  errors: string[];
  changes: { cluster_id: string; before: string[]; after: string[] }[];
  relabel_cluster_ids: string[];
  reused_label_cluster_ids: string[];
}
export interface Annotation {
  verdict: string;
  reviewer?: string;
  rationale: string;
  evidence: Evidence[];
  saw_model_assessment: boolean;
}
export interface ReviewItem {
  id: string;
  kind: "connection" | "gap";
  scope: string;
  paper_ids: string[];
  cluster_ids: string[];
  claim: string | null;
  proposed_test: string | null;
  papers: {
    id: string;
    title: string;
    year: number | null;
    source_field: string;
    source_text: string;
  }[];
  annotation: Annotation | null;
  model_assessment?: { decision: string; reason?: string };
}
export interface ReviewPack {
  run_id: string;
  version_token: string;
  question: string;
  sample_mode: boolean;
  items: ReviewItem[];
  summary: {
    total: number;
    reviewed: number;
    pending: number;
    supported: number;
    unsupported: number;
    uncertain: number;
    semantic_accuracy: null;
  };
}
export interface AgentAssessment {
  item_id: string;
  status: "assessed" | "needs_hypothesis" | "insufficient_sources" | "sample";
  verdict: "supported" | "unsupported" | "uncertain" | null;
  scores: {
    source_support: number;
    relevance: number;
    testability: number;
  } | null;
  total: number | null;
  reason: string;
  limitations: string[];
  evidence: Evidence[];
}
export interface AgentReviewReport {
  report_id: string;
  provenance: "model";
  sample_mode: boolean;
  model: string | null;
  created_at: string;
  items: AgentAssessment[];
  limitations: string[];
}
export interface SearchPlan {
  question: string;
  criteria: {
    topic: string;
    year_from: number | null;
    year_to: number | null;
    min_citations: number | null;
    paper_types: string[];
  };
  queries: string[];
  effort: string;
  max_papers: number;
  used_defaults: string[];
  rationale: string | null;
}
export interface SearchResult {
  search_id: string;
  status: "ok" | "need_topic" | "no_results";
  sample_mode: boolean;
  message_to_user: string | null;
  plan: SearchPlan | null;
  papers: (Paper & {
    citation_count?: number | null;
    is_review?: boolean | null;
  })[];
  backup_papers?: Paper[];
  summary: string | null;
  follow_up_question: string | null;
  warnings: string[];
}
export type Selection = {
  type: "paper" | "cluster" | "connection" | "gap";
  id: string;
};
export type Filter = "all" | "connections" | "gaps";

export interface FeedbackTarget {
  kind: "cluster" | "connection" | "gap";
  id: string;
}
export interface FeedbackState {
  version_token?: string;
  votes: Record<string, { vote: "up" | "down"; at: string }>;
  messages: { id: string; role: "user" | "assistant"; text: string }[];
  update?: {
    status: "paused" | "complete" | "dismissed";
    run_id: string;
    active_run_id: string;
    can_resume: boolean;
    completed: string[];
    pending: string[];
    issue: { code: string; reason: string; next_step: string } | null;
    message: string;
  };
}
