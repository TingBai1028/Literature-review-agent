import { useCallback, useEffect, useState } from "react";
import { Check, Eye, Quote } from "lucide-react";
import { request, messageOf } from "../api";
import type {
  AgentReviewReport,
  Evidence,
  MapResult,
  ReviewItem,
  ReviewPack,
} from "../types";
import { AgentReview } from "./AgentReview";
export function ReviewPanel({
  map,
  timeout,
}: {
  map: MapResult;
  timeout: number;
}) {
  const [pack, setPack] = useState<ReviewPack | null>(null);
  const [selected, setSelected] = useState("");
  const [error, setError] = useState("");
  const [agentReport, setAgentReport] = useState<AgentReviewReport | null>(
    null,
  );
  const [seenItems, setSeenItems] = useState<Set<string>>(new Set());
  const recordSeen = useCallback((id: string) => {
    setSeenItems((old) => (old.has(id) ? old : new Set([...old, id])));
  }, []);
  useEffect(() => {
    const abort = new AbortController();
    request<ReviewPack>(`/cluster/${map.run_id}/review`, {
      signal: abort.signal,
    })
      .then((p) => {
        if (!abort.signal.aborted) {
          setPack(p);
          setSelected(p.items[0]?.id ?? "");
        }
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(messageOf(e));
      });
    return () => abort.abort();
  }, [map.run_id]);
  const item = pack?.items.find((i) => i.id === selected);
  return (
    <section className="review-workspace" aria-label="Human review workspace">
      <aside className="review-queue">
        <h2>Review items</h2>
        <p className="muted small">
          {pack
            ? `${pack.summary.reviewed} / ${pack.summary.total} done`
            : "Preparing sources…"}
        </p>
        <p className="muted small">
          Read the sources first, then give your judgement. Model grades are hidden by default.
        </p>
        {pack?.items.map((i, n) => (
          <button
            className={`review-item ${selected === i.id ? "selected" : ""}`}
            onClick={() => {
              setSelected(i.id);
              setError("");
            }}
            key={i.id}
          >
            <span>
              {i.annotation ? (
                <Check size={15} />
              ) : (
                String(n + 1).padStart(2, "0")
              )}
            </span>
            <div>
              <strong>
                {i.kind === "gap"
                  ? i.scope === "main_side"
                    ? "Main ↔ side candidate"
                    : "Within-cluster gap candidate"
                  : "Connection check"}
              </strong>
              <small>{i.papers.map((p) => p.title).join(" / ")}</small>
            </div>
          </button>
        ))}
        {pack && !pack.items.length && (
          <p className="muted">This version has no paper pairs to check.</p>
        )}
      </aside>
      <div className="review-detail">
        {item && pack ? (
          <ReviewForm
            key={item.id}
            item={item}
            map={map}
            token={pack.version_token}
            agentReport={agentReport}
            onAgentReport={setAgentReport}
            wasSeen={seenItems.has(item.id)}
            recordSeen={recordSeen}
            timeout={timeout}
            onSaved={(annotation, summary) =>
              setPack((old) =>
                old
                  ? {
                      ...old,
                      summary,
                      items: old.items.map((i) =>
                        i.id === item.id ? { ...i, annotation } : i,
                      ),
                    }
                  : old,
              )
            }
          />
        ) : (
          <div className="center-message">
            {error || "Choose a review item."}
          </div>
        )}
      </div>
    </section>
  );
}
function ReviewForm({
  item,
  map,
  token,
  onSaved,
  agentReport,
  onAgentReport,
  wasSeen,
  recordSeen,
  timeout,
}: {
  item: ReviewItem;
  map: MapResult;
  token: string;
  agentReport: AgentReviewReport | null;
  onAgentReport: (report: AgentReviewReport) => void;
  wasSeen: boolean;
  recordSeen: (id: string) => void;
  timeout: number;
  onSaved: (
    annotation: NonNullable<ReviewItem["annotation"]>,
    summary: ReviewPack["summary"],
  ) => void;
}) {
  const [verdict, setVerdict] = useState(item.annotation?.verdict ?? "");
  const [reviewer, setReviewer] = useState(item.annotation?.reviewer ?? "");
  const [rationale, setRationale] = useState(item.annotation?.rationale ?? "");
  const [evidence, setEvidence] = useState<Evidence[]>(
    item.annotation?.evidence ?? [],
  );
  const [revealed, setRevealed] = useState(
    item.annotation?.saw_model_assessment ?? false,
  );
  const [assessment, setAssessment] =
    useState<ReviewItem["model_assessment"]>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const markSeen = useCallback(
    () => recordSeen(item.id),
    [item.id, recordSeen],
  );
  const quote = (id: string, source: string) => {
    const selected = window.getSelection()?.toString();
    const text =
      selected && source.includes(selected) ? selected : source.slice(0, 400);
    setEvidence((old) => [
      ...old.filter((e) => e.paper_id !== id),
      { paper_id: id, quote: text },
    ]);
    setSaved(false);
  };
  const submit = async () => {
    setError("");
    setSaved(false);
    if (!verdict) {
      setError("Choose a judgement: supported, not supported or insufficient evidence.");
      return;
    }
    if (!reviewer.trim()) {
      setError("Enter a reviewer name or ID; initials are fine.");
      return;
    }
    if (rationale.trim().length < 10) {
      setError("The reason needs at least 10 characters; add the specific basis.");
      return;
    }
    if (
      verdict !== "uncertain" &&
      item.paper_ids.some(
        (id) =>
          !evidence.some(
            (e) => e.paper_id === id && e.quote.trim().length >= 20,
          ),
      )
    ) {
      setError("A definite judgement needs a quote from each paper, at least 20 characters each.");
      return;
    }
    setBusy(true);
    try {
      const out = await request<{
        annotation: NonNullable<ReviewItem["annotation"]>;
        summary: ReviewPack["summary"];
      }>(`/cluster/${map.run_id}/review/${encodeURIComponent(item.id)}`, {
        method: "POST",
        body: {
          expected_version_token: token,
          verdict,
          reviewer,
          rationale,
          evidence,
          saw_model_assessment: revealed || wasSeen,
        },
      });
      onSaved(out.annotation, out.summary);
      setSaved(true);
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <div className="review-title">
        <h2>{item.kind === "gap" ? "Check a testable hypothesis" : "Check a paper connection"}</h2>
        <button
          className="quiet-button"
          onClick={async () => {
            try {
              const all = await request<ReviewPack>(
                `/cluster/${map.run_id}/review?reveal=true`,
              );
              setAssessment(
                all.items.find((i) => i.id === item.id)?.model_assessment,
              );
              setRevealed(true);
              markSeen();
            } catch (e) {
              setError(messageOf(e));
            }
          }}
        >
          <Eye size={15} />
          Show model judgement
        </button>
      </div>
      <p className="review-question">
        {item.claim || `From the two sources, can you state a testable hypothesis that fits this research question?`}
      </p>
      {!item.claim && <p className="muted">{map.question}</p>}
      {item.proposed_test && (
        <p className="muted">Proposed experiment: {item.proposed_test}</p>
      )}
      <p className="muted small">
        Judge the specific connection or hypothesis between the two papers, not the quality of each paper. "Supported" does not confirm a global research gap.
      </p>
      {!item.claim && (
        <p className="notice">
          There is only a candidate pair so far, with no concrete hypothesis. You can note exploratory comments; state a testable question before confirming a scientific conclusion.
        </p>
      )}
      <AgentReview
        map={map}
        token={token}
        item={item}
        report={agentReport}
        onReport={onAgentReport}
        onSeen={markSeen}
        timeout={timeout}
      />
      {assessment && (
        <div className="notice">
          <strong>Model judgement: {assessment.decision}</strong>
          <p>
            {assessment.reason ||
              "This is a kept connection; the sources and human review decide."}
          </p>
        </div>
      )}
      <div className="review-sources">
        {item.papers.map((p) => (
          <article key={p.id}>
            <p className="source-caption">
              {p.year ?? ""} ·{" "}
              {p.source_field === "full_text" ? "Full text provided" : "Original abstract"}
            </p>
            <h3>{p.title}</h3>
            <div className="review-source-text">
              {p.source_text || "No text to check"}
            </div>
            <button
              className="text-button"
              onClick={() => quote(p.id, p.source_text)}
              disabled={!p.source_text}
            >
              <Quote size={14} />
              Quote the selection or the first passage
            </button>
            {evidence.find((e) => e.paper_id === p.id) && (
              <label className="form-field small">
                Selected quote
                <textarea
                  aria-label={`Quote ${p.id}`}
                  rows={3}
                  value={evidence.find((e) => e.paper_id === p.id)?.quote}
                  onChange={(e) =>
                    setEvidence((old) =>
                      old.map((q) =>
                        q.paper_id === p.id
                          ? { ...q, quote: e.target.value }
                          : q,
                      ),
                    )
                  }
                />
              </label>
            )}
          </article>
        ))}
      </div>
      <form
        className="review-form"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <fieldset>
          <legend>Your judgement</legend>
          <div className="judgment-options">
            {[
              ["supported", "Supported"],
              ["unsupported", "Not supported"],
              ["uncertain", "Insufficient evidence"],
            ].map(([v, label]) => (
              <label key={v}>
                <input
                  type="radio"
                  name="verdict"
                  value={v}
                  checked={verdict === v}
                  onChange={() => {
                    setVerdict(v);
                    setSaved(false);
                  }}
                />
                {label}
              </label>
            ))}
          </div>
        </fieldset>
        <label className="form-field">
          Reviewer
          <input
            value={reviewer}
            onChange={(e) => {
              setReviewer(e.target.value);
              setSaved(false);
              setError("");
            }}
            placeholder="Your name or reviewer ID"
            maxLength={80}
          />
        </label>
        <label className="form-field">
          Reason
          <textarea
            value={rationale}
            onChange={(e) => {
              setRationale(e.target.value);
              setSaved(false);
              setError("");
            }}
            rows={3}
            placeholder="Explain the basis in tasks, methods, data or evaluation setup"
          />
        </label>
        {error && (
          <p className="inline-error" role="alert">
            {error}
          </p>
        )}
        <div className="review-submit">
          <span className="muted small">
            {saved ? "Judgement saved to the active version." : "Nothing is saved until you submit."}
          </span>
          <button className="primary-button" disabled={busy} type="submit">
            {busy ? "Saving…" : "Save judgement"}
          </button>
        </div>
      </form>
    </>
  );
}
