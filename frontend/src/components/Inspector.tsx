import { useEffect, useState, type ReactNode } from "react";
import { ArrowUpRight, ArrowRight, BookOpen } from "lucide-react";
import { request, messageOf } from "../api";
import { roleName } from "./TopicSidebar";
import type {
  Candidate,
  Evidence,
  MapResult,
  Move,
  Paper,
  Selection,
} from "../types";
const relationNames: Record<string, string> = {
  builds_on: "Builds on",
  same_method_different_domain: "Same method · different domain",
  same_problem_different_method: "Same problem · different method",
  benchmarks_against: "Benchmarks against",
  directly_cites: "Directly cites",
};
function SourceQuotes({
  evidence,
  papers,
  showTitles = true,
}: {
  evidence: Evidence[];
  papers: Paper[];
  showTitles?: boolean;
}) {
  return (
    <div className="source-quotes">
      {evidence.map((e, i) => (
        <div key={i}>
          {showTitles && (
            <p className="source-caption">
              {papers.find((p) => p.id === e.paper_id)?.title ?? e.paper_id}
            </p>
          )}
          <blockquote>{e.quote}</blockquote>
        </div>
      ))}
    </div>
  );
}
export function Inspector({
  map,
  papers,
  selection,
  onSelect,
  moves,
  onMove,
  canEdit,
  onReview,
  children,
}: {
  map: MapResult;
  papers: Paper[];
  selection: Selection | null;
  onSelect: (s: Selection) => void;
  moves: Move[];
  onMove: (paper: string, target: string) => void;
  canEdit: boolean;
  onReview: () => void;
  children?: ReactNode; // shown under the selection, e.g. its provenance
}) {
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [error, setError] = useState("");
  const [full, setFull] = useState<Paper | null>(null);
  const paper =
    selection?.type === "paper"
      ? papers.find((p) => p.id === selection.id)
      : undefined;
  const cluster = map.clusters.find((c) =>
    c.paper_ids.includes(paper?.id ?? ""),
  );
  const detail = cluster?.paper_details?.find((d) => d.paper_id === paper?.id);
  useEffect(() => {
    setCandidates([]);
    setError("");
    setFull(null);
    if (!paper || cluster?.kind === "main" || cluster?.kind === "foundation")
      return;
    const abort = new AbortController();
    request<{ candidates: Candidate[] }>(
      `/cluster/${map.run_id}/regenerate/candidates?paper_id=${encodeURIComponent(paper.id)}`,
      { signal: abort.signal },
    )
      .then((r) => {
        if (!abort.signal.aborted) setCandidates(r.candidates);
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(messageOf(e));
      });
    return () => abort.abort();
  }, [paper?.id, cluster?.kind, map.run_id]);
  const connection =
    selection?.type === "connection"
      ? map.connections.find((c) => c.id === selection.id)
      : null;
  const gap =
    selection?.type === "gap"
      ? map.gaps.find((g) => g.id === selection.id)
      : null;
  const topic =
    selection?.type === "cluster"
      ? map.clusters.find((c) => c.id === selection.id)
      : null;
  const card = map.cluster_cards?.find((c) => c.cluster_id === topic?.id);
  return (
    <aside className="inspector" aria-label="Details and evidence">
      <h2 className="inspector-heading">
        {paper
          ? "Paper details"
          : connection
            ? "Connection evidence"
            : gap
              ? "Hypothesis"
              : topic
                ? "Topic details"
                : "Sources and evidence"}
      </h2>
      {paper ? (
        <>
          <h3 className="paper-title">{paper.title}</h3>
          <p className="paper-meta">
            {paper.year ?? "Year unknown"}
            <span>·</span>
            {paper.source === "openalex" ? "OpenAlex" : paper.source}
          </p>
          {!!detail?.keywords.length && (
            <div className="keywords">
              {detail.keywords.map((k) => (
                <span key={k}>{k}</span>
              ))}
            </div>
          )}
          <section className="inspector-section">
            <h3>Source evidence</h3>
            {detail?.evidence.length ? (
              <div className="paper-evidence">
                <SourceQuotes
                  evidence={detail.evidence}
                  papers={papers}
                  showTitles={false}
                />
              </div>
            ) : paper.abstract ? (
              <blockquote>{paper.abstract}</blockquote>
            ) : (
              <p className="muted">This record has no abstract to check.</p>
            )}
            {paper.abstract && (
              <details>
                <summary>Show full abstract</summary>
                <p className="original-text">{paper.abstract}</p>
              </details>
            )}
            <button
              className="text-button small"
              onClick={async () => {
                try {
                  setFull(
                    await request<Paper>(
                      `/cluster/${map.run_id}/papers/${encodeURIComponent(paper.id)}`,
                    ),
                  );
                } catch (e) {
                  setError(messageOf(e));
                }
              }}
            >
              Full-text status
            </button>
            {full && (
              <p className="muted small">
                {full.full_text
                  ? `Full text provided, ${full.full_text.length.toLocaleString()} characters.`
                  : "No full text provided; checks used the available abstract."}
              </p>
            )}
            {full?.full_text && (
              <details>
                <summary>Show full text</summary>
                <p className="original-text">{full.full_text}</p>
              </details>
            )}
          </section>
          <section className="inspector-section">
            <h3>Cluster and alternatives</h3>
            <div className="membership">
              <span className="muted">Current cluster</span>
              <strong>
                {cluster?.kind === "side" || !cluster?.kind
                  ? cluster?.label
                  : roleName(cluster)}
              </strong>
            </div>
            {cluster?.kind === "main" || cluster?.kind === "foundation" ? (
              <p className="muted small">
                Main and foundation clusters are set by relevance and citation rules; their members are fixed
              </p>
            ) : (
              <>
                {(detail?.also_related ?? []).map((a) => (
                  <div key={a.cluster_id} className="alternative-row">
                    <span>
                      {map.clusters.find((c) => c.id === a.cluster_id)?.label ??
                        a.cluster_id}
                    </span>
                    <span>{a.similarity.toFixed(2)}</span>
                  </div>
                ))}
                <p className="muted small">
                  Similarity is a hint of relatedness, not another cluster membership or a verified scientific connection.
                </p>
                <label className="form-field small">
                  Move to
                  <select
                    aria-label="Choose where to move"
                    disabled={!canEdit}
                    value={
                      moves.find((m) => m.paper_id === paper.id)
                        ?.target_cluster_id ?? ""
                    }
                    onChange={(e) => onMove(paper.id, e.target.value)}
                  >
                    <option value="">Keep current cluster</option>
                    {candidates.map((c) => (
                      <option
                        key={c.target_cluster_id}
                        value={c.target_cluster_id}
                        disabled={!c.eligible}
                      >
                        {
                          map.clusters.find((x) => x.id === c.target_cluster_id)
                            ?.label
                        }{" "}
                        · {c.target_similarity.toFixed(2)}
                        {c.eligible ? "" : " · fails numeric constraints"}
                      </option>
                    ))}
                  </select>
                </label>
                {!canEdit && (
                  <p className="muted small">
                    Open the active version, in the server's mode, to preview moves.
                  </p>
                )}
              </>
            )}
          </section>
          {/^(W\d+)$/.test(paper.id) && (
            <a
              className="source-link"
              href={`https://openalex.org/${paper.id}`}
              target="_blank"
              rel="noreferrer"
            >
              <ArrowUpRight size={17} />View on OpenAlex
            </a>
          )}
        </>
      ) : topic ? (
        <>
          <h3 className="paper-title">{topic.label}</h3>
          <p className="paper-meta">
            {roleName(topic)} · {topic.paper_ids.length} papers
          </p>
          {topic.role_reason && <p className="small">{topic.role_reason}</p>}
          {card && (
            <section className="inspector-section cluster-card">
              <h3>
                Cluster card ·{" "}
                {card.analysis_depth === "full_pdf"
                  ? `Full-text analysis (${card.papers_with_full_text ?? 0} with full text)`
                  : "Metadata analysis"}
              </h3>
              <p>{card.summary}</p>
              <p className="muted small">
                {card.year_range
                  ? `${card.year_range[0]}–${card.year_range[1]}`
                  : "Year unknown"}
                {card.citations?.max != null &&
                  ` · median citations ${card.citations.median} · max ${card.citations.max}`}
              </p>
              {card.keywords.length > 0 && (
                <p className="small">Keywords: {card.keywords.join(", ")}</p>
              )}
            </section>
          )}
          <p className="muted small">{topic.rationale}</p>
          <div className="paper-list">
            {topic.paper_ids.map((id) => (
              <button key={id} onClick={() => onSelect({ type: "paper", id })}>
                <BookOpen size={16} />
                <span>{papers.find((p) => p.id === id)?.title ?? id}</span>
                <ArrowRight size={15} />
              </button>
            ))}
          </div>
        </>
      ) : connection ? (
        <>
          <h3 className="finding-title">
            {connection.reason_short ?? connection.description}
          </h3>
          <p className="muted small">
            {relationNames[connection.relation ?? ""] ?? "Connection"} ·{" "}
            {connection.kind === "within_cluster" ? "Within cluster" : "Across clusters"} ·{" "}
            {map.sample_mode
              ? "Sample placeholder"
              : "Passed an independent source check; still needs human review"}
          </p>
          {connection.reason_long && <p>{connection.reason_long}</p>}
          {!!connection.evidence_notes?.length && (
            <section className="inspector-section">
              <h3>Basis</h3>
              <ul className="evidence-notes">
                {connection.evidence_notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </section>
          )}
          <SourceQuotes evidence={connection.evidence} papers={papers} />
          {connection.similarity != null && (
            <p className="muted small">
              Similarity {connection.similarity.toFixed(2)}
            </p>
          )}
          <button className="secondary-button" onClick={onReview}>
            Open in human review
          </button>
        </>
      ) : gap ? (
        <>
          <h3 className="finding-title">{gap.description}</h3>
          <p className="small">
            Between:
            {gap.between_paper_ids
              .map((id) => papers.find((p) => p.id === id)?.title ?? id)
              .join(" ↔ ")}{" "}
            ·{" "}
            {map.clusters.find((c) => c.id === gap.cluster_id)?.label ??
              gap.cluster_id}
          </p>
          <p className="hypothesis-label">
            {map.sample_mode ? "Sample placeholder" : "Hypothesis to verify"} ·{" "}
            {gap.scope === "main_side" ? "Main and side cluster" : "Within cluster"}
            {gap.gap_type && (
              <>
                {" "}
                ·{" "}
                <span className="gap-badge">
                  {gap.gap_type === "explicit" ? "Stated by authors" : "Inferred"}
                </span>
              </>
            )}
            {gap.label && (
              <>
                {" "}
                ·{" "}
                {(
                  {
                    novel: "Novel",
                    known_open: "Known, still open",
                  } as Record<string, string>
                )[gap.label] ?? gap.label}
                {!map.sample_mode &&
                  gap.label === "novel" &&
                  gap.coverage_status !== "not_filled" && (
                  <span
                    className="gap-badge unverified"
                    title="The coverage search did not run, so no search has checked whether this is already studied. Unverified gaps are listed after verified ones."
                  >
                    novelty unverified
                  </span>
                )}
              </>
            )}
          </p>
          <p>{gap.why_it_matters}</p>
          {gap.label_reason && (
            <p className="muted small">{gap.label_reason}</p>
          )}
          {gap.proposed_test && (
            <section className="inspector-section">
              <h3>Proposed experiment</h3>
              <p>{gap.proposed_test}</p>
            </section>
          )}
          <SourceQuotes evidence={gap.evidence} papers={papers} />
          {gap.coverage && (
            <section className="inspector-section">
              <h3>Prior-work coverage check</h3>
              <p>
                {(
                  {
                    unavailable: "Search unavailable",
                    inconclusive: "Coverage inconclusive",
                    no_address_found_in_checked_sources:
                      "No answer found in the checked sources",
                    addressed: "Already addressed by a source",
                  } as Record<string, string>
                )[gap.coverage.status] ?? gap.coverage.status}
              </p>
              <p className="muted small">{gap.coverage.scope}</p>
              {gap.coverage.searches.map((s, i) => (
                <p className="muted small" key={i}>
                  {s.query} · {s.papers.length} results
                </p>
              ))}
            </section>
          )}
          <button className="secondary-button" onClick={onReview}>
            Open in human review
          </button>
        </>
      ) : (
        <div className="inspector-placeholder">
          <BookOpen size={28} />
          <p>Click a paper, topic or connection to see its sources and checks.</p>
          <button className="text-button" onClick={onReview}>
            Review candidates
          </button>
        </div>
      )}
      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
      {children}
    </aside>
  );
}
