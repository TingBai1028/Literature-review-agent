import { useEffect, useRef, useState } from "react";
import { Bot, LoaderCircle } from "lucide-react";
import { request, messageOf } from "../api";
import type { AgentReviewReport, MapResult, ReviewItem } from "../types";

export function AgentReview({
  map,
  token,
  item,
  report,
  onReport,
  onSeen,
  timeout,
}: {
  map: MapResult;
  token: string;
  item: ReviewItem;
  report: AgentReviewReport | null;
  onReport: (report: AgentReviewReport) => void;
  onSeen: () => void;
  timeout: number;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const running = useRef(false);
  const assessment = report?.items.find((i) => i.item_id === item.id);
  useEffect(() => {
    if (assessment) onSeen();
  }, [assessment, onSeen]);
  const load = async (run: boolean) => {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const out = await request<{
        report: AgentReviewReport | null;
        reused?: boolean;
      }>(`/cluster/${map.run_id}/review-agent`, {
        method: run ? "POST" : "GET",
        body: run ? { expected_version_token: token } : undefined,
        timeout,
      });
      if (out.report) {
        onReport(out.report);
        setMessage(
          out.reused ? "Loaded this version's existing review; the model was not called again." : "",
        );
      } else setMessage("This version has no AI grades yet. Click \"AI grading\" to create them.");
    } catch (e) {
      setError(messageOf(e));
    } finally {
      running.current = false;
      setBusy(false);
    }
  };
  return (
    <section className="agent-review" aria-label="AI review suggestions">
      <div className="agent-review-header">
        <h3>
          <Bot size={18} />
          AI review suggestions
        </h3>
        <div className="agent-review-actions">
          <button
            className="quiet-button"
            disabled={busy}
            onClick={() => void load(false)}
          >
            Show existing grades
          </button>
          <button
            className="secondary-button"
            disabled={busy}
            onClick={() => void load(true)}
          >
            {busy ? (
              <LoaderCircle size={15} className="spin" />
            ) : (
              <Bot size={15} />
            )}
            {busy ? "Reviewing…" : "AI grading"}
          </button>
        </div>
      </div>
      <p className="muted small">
        Grades each connection and hypothesis in this version and keeps independent source quotes. Human reviews are saved separately.
      </p>
      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
      {message && (
        <p className="muted small" role="status">
          {message}
        </p>
      )}
      {assessment && (
        <div className="agent-review-result">
          <strong>
            {assessment.status === "sample"
              ? "Sample flow · not graded"
              : assessment.status === "needs_hypothesis"
                ? "Needs a concrete hypothesis · not graded"
                : assessment.status === "insufficient_sources"
                  ? "Missing source text · not graded"
                  : `AI suggestion: ${({ supported: "Supported", unsupported: "Not supported", uncertain: "Insufficient evidence" } as const)[assessment.verdict!]} · ${assessment.total}/9`}
          </strong>
          {assessment.scores && (
            <dl className="agent-review-scores">
              <div>
                <dt>Source support</dt>
                <dd>{assessment.scores.source_support}/3</dd>
              </div>
              <div>
                <dt>Relevance to the question</dt>
                <dd>{assessment.scores.relevance}/3</dd>
              </div>
              <div>
                <dt>Testability</dt>
                <dd>{assessment.scores.testability}/3</dd>
              </div>
            </dl>
          )}
          <p>{assessment.reason}</p>
          {assessment.limitations.length > 0 && (
            <ul>
              {assessment.limitations.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ul>
          )}
          {assessment.evidence.length > 0 && (
            <details>
              <summary>
                Show the agent's source quotes ({assessment.evidence.length})
              </summary>
              {assessment.evidence.map((e, i) => (
                <figure key={i}>
                  <figcaption>
                    {item.papers.find((p) => p.id === e.paper_id)?.title ??
                      e.paper_id}
                  </figcaption>
                  <blockquote>{e.quote}</blockquote>
                </figure>
              ))}
            </details>
          )}
          <p className="muted small">
            AI suggestions only support human review. Grades are not accuracy and do not confirm global novelty.
            {report?.model && `Model: ${report.model}`}
          </p>
        </div>
      )}
    </section>
  );
}
