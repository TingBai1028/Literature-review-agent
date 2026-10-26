import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { request, messageOf } from "../api";
import { newRunId, useRunEvents } from "../events";
import type { Paper, SearchResult } from "../types";
export function useSearchReview(
  query: string,
  effort: string,
  timeout: number,
) {
  const [result, setResult] = useState<SearchResult | null>(null);
  const [kept, setKept] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [searchId, setSearchId] = useState<string | null>(null);
  const events = useRunEvents(searchId); // live retriever counter and feed (specs A2, A3)
  const run = async (feedback?: string) => {
    setLoading(true);
    setError("");
    const id = newRunId();
    setSearchId(id);
    try {
      const replan = feedback && result?.plan;
      const out = await request<SearchResult>("/search", {
        method: "POST",
        body: {
          run_id: id,
          input: {
            query: replan ? result.plan!.question : query.trim(),
            effort,
            ...(replan ? { feedback, previous_plan: result.plan } : {}),
          },
        },
        timeout,
      });
      setResult(out);
      setKept(new Set(out.papers.map((p) => p.id)));
      return true;
    } catch (e) {
      setError(messageOf(e));
      return false;
    } finally {
      setLoading(false);
    }
  };
  const toggle = (id: string) =>
    setKept((old) => {
      const next = new Set(old);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const selected: Paper[] = (result?.papers ?? []).filter((p) =>
    kept.has(p.id),
  );
  return {
    result,
    kept,
    selected,
    loading,
    error,
    run,
    toggle,
    events,
    reset: () => setResult(null),
  };
}
const describe = (plan: NonNullable<SearchResult["plan"]>) => {
  const c = plan.criteria;
  const defaulted = new Set(plan.used_defaults.map((d) => d.split("=")[0]));
  const mark = (name: string) => (defaulted.has(name) ? " (default)" : "");
  const years = `${c.year_from ?? "…"}–${c.year_to ?? "now"}${mark("year_from")}`;
  const types =
    c.paper_types.length === 1
      ? c.paper_types[0] === "review"
        ? "Reviews only"
        : "Primary research only"
      : "Reviews + primary research";
  return [
    `Topic: ${c.topic}`,
    `Years: ${years}`,
    `Types: ${types}${mark("paper_types")}`,
    ...(c.min_citations ? [`Citations ≥ ${c.min_citations}`] : []),
  ];
};
export function SearchReview({
  search,
}: {
  search: ReturnType<typeof useSearchReview>;
}) {
  const [feedback, setFeedback] = useState("");
  const { result, kept, loading } = search;
  if (!result) return null;
  if (result.status !== "ok")
    return (
      <p className="search-message" role="status">
        {result.message_to_user}
      </p>
    );
  const all = kept.size === result.papers.length;
  return (
    <section className="search-review" aria-label="Search result review">
      <p className="search-summary">{result.summary}</p>
      {result.plan && (
        <div className="search-plan">
          <div className="plan-criteria">
            {describe(result.plan).map((text) => (
              <span key={text}>{text}</span>
            ))}
          </div>
          <p className="muted small">
            Queries: {result.plan.queries.join(" · ")}
          </p>
        </div>
      )}
      {result.warnings.map((w) => (
        <p className="inline-error small" key={w}>
          {w}
        </p>
      ))}
      <div className="search-list-heading">
        <strong>
          Keeping {kept.size} / {result.papers.length} papers
        </strong>
        <button
          type="button"
          className="text-button small"
          onClick={() =>
            result.papers.forEach(
              (p) => kept.has(p.id) === all && search.toggle(p.id),
            )
          }
        >
          {all ? "Deselect all" : "Keep all"}
        </button>
      </div>
      <ul className="search-papers">
        {result.papers.map((p) => (
          <li key={p.id}>
            <label>
              <input
                type="checkbox"
                checked={kept.has(p.id)}
                onChange={() => search.toggle(p.id)}
              />
              <span>
                <strong>{p.title}</strong>
                <small>
                  {[
                    p.year,
                    p.is_review ? "Review" : null,
                    p.citation_count != null
                      ? `${p.citation_count} citations`
                      : null,
                    p.abstract ? null : "No abstract",
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </small>
              </span>
            </label>
          </li>
        ))}
      </ul>
      <div className="search-feedback">
        <label className="form-field">
          {result.follow_up_question}
          <textarea
            rows={2}
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            placeholder="For example: only primary research from 2023 onwards"
          />
        </label>
        <button
          type="button"
          className="secondary-button"
          disabled={loading || !feedback.trim()}
          onClick={() =>
            void search.run(feedback.trim()).then((ok) => ok && setFeedback(""))
          }
        >
          <RefreshCw size={14} />
          Search again with feedback
        </button>
      </div>
    </section>
  );
}
