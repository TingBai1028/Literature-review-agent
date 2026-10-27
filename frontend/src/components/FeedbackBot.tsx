import { useEffect, useRef, useState } from "react";
import {
  GripHorizontal,
  Check,
  Clock3,
  LoaderCircle,
  MessageCircle,
  Send,
  X,
} from "lucide-react";
import { messageOf } from "../api";
import { feedbackSteps } from "../feedbackWorkflow";
import type { FeedbackState, MapResult } from "../types";

export function FeedbackBot({
  map,
  feedback,
  busy,
  editable,
  ready,
  openRequest,
  onSubmit,
  onResume,
  onKeepCurrent,
  onViewDraft,
  progress,
}: {
  map?: MapResult;
  feedback: FeedbackState;
  busy: boolean;
  editable: boolean;
  ready: boolean;
  openRequest: number;
  onSubmit: (text: string) => Promise<void>;
  onResume: () => Promise<void>;
  onKeepCurrent: () => Promise<void>;
  onViewDraft: () => void;
  progress: string;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [position, setPosition] = useState<{ x: number; y: number } | null>(
    null,
  );
  const prompted = useRef("");
  const update = feedback.update;
  const paused = update?.status === "paused";
  const showOutcome =
    !!update &&
    update.status !== "dismissed" &&
    (paused || update.pending.length > 0);
  const panel = useRef<HTMLDivElement>(null);
  const messages = useRef<HTMLDivElement>(null);
  const drag = useRef<{
    x: number;
    y: number;
    left: number;
    top: number;
  } | null>(null);
  const clamp = (x: number, y: number) => ({
    x: Math.max(
      8,
      Math.min(x, innerWidth - (panel.current?.offsetWidth ?? 340) - 8),
    ),
    y: Math.max(
      8,
      Math.min(y, innerHeight - (panel.current?.offsetHeight ?? 400) - 8),
    ),
  });
  useEffect(() => {
    const prompt = paused ? update!.run_id : map?.version_token;
    if (map && (ready || paused) && !busy && prompted.current !== prompt) {
      prompted.current = prompt!;
      setOpen(true);
      setError("");
    }
  }, [map?.version_token, ready, busy, paused, update?.run_id]);
  useEffect(() => {
    if (openRequest) setOpen(true);
  }, [openRequest]);
  useEffect(() => {
    if (open) setPosition((p) => (p ? clamp(p.x, p.y) : null));
  }, [open, update?.run_id, update?.status]);
  useEffect(() => {
    const resize = () => setPosition((p) => (p ? clamp(p.x, p.y) : null));
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);
  useEffect(() => {
    if (messages.current)
      messages.current.scrollTop = messages.current.scrollHeight;
  }, [feedback.messages, busy, open]);
  if (!map) return null;
  return (
    <div
      ref={panel}
      className={`feedback-bot ${open ? "open" : "closed"}`}
      style={
        position
          ? { left: position.x, top: position.y, right: "auto", bottom: "auto" }
          : undefined
      }
    >
      {open ? (
        <section aria-label="Graph feedback assistant">
          <header>
            <div
              className="bot-drag"
              role="button"
              tabIndex={0}
              aria-label="Move feedback assistant"
              title="Drag to move; use arrow keys when focused"
              onPointerDown={(event) => {
                const box = panel.current!.getBoundingClientRect();
                drag.current = {
                  x: event.clientX,
                  y: event.clientY,
                  left: box.left,
                  top: box.top,
                };
                event.currentTarget.setPointerCapture(event.pointerId);
              }}
              onPointerMove={(event) => {
                if (drag.current)
                  setPosition(
                    clamp(
                      drag.current.left + event.clientX - drag.current.x,
                      drag.current.top + event.clientY - drag.current.y,
                    ),
                  );
              }}
              onPointerUp={() => {
                drag.current = null;
              }}
              onPointerCancel={() => {
                drag.current = null;
              }}
              onKeyDown={(event) => {
                if (
                  !["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(
                    event.key,
                  )
                )
                  return;
                event.preventDefault();
                const box = panel.current!.getBoundingClientRect();
                setPosition(
                  clamp(
                    box.left +
                      (event.key === "ArrowRight"
                        ? 20
                        : event.key === "ArrowLeft"
                          ? -20
                          : 0),
                    box.top +
                      (event.key === "ArrowDown"
                        ? 20
                        : event.key === "ArrowUp"
                          ? -20
                          : 0),
                  ),
                );
              }}
            >
              <MessageCircle size={18} />
              <strong>Graph feedback</strong>
              <GripHorizontal size={16} />
            </div>
            <button
              className="icon-button"
              aria-label="Close feedback assistant"
              onClick={() => setOpen(false)}
            >
              <X size={18} />
            </button>
          </header>
          <div className="bot-messages" ref={messages} aria-live="polite">
            {!feedback.messages.length && !busy && (
              <p className="bot-message assistant">
                {ready
                  ? "Your graph is ready. What would you like to improve?"
                  : "Finish building the graph to give feedback."}
              </p>
            )}
            {feedback.messages.map((message) => (
              <p className={`bot-message ${message.role}`} key={message.id}>
                {message.text}
              </p>
            ))}
            {busy && (
              <p className="bot-message assistant" role="status">
                <LoaderCircle size={14} className="spin" />{" "}
                {progress || "Applying your feedback…"}
              </p>
            )}
          </div>
          {showOutcome && (
            <div
              className="bot-update"
              role="region"
              aria-label="Feedback update status"
            >
              <div className="bot-update-details">
                <strong>
                  {busy
                    ? "Working on the saved update…"
                    : paused
                      ? "Update paused"
                      : "Graph updated · checks pending"}
                </strong>
                <p>
                  {paused
                    ? map.run_id === update!.run_id &&
                      map.run_id !== update!.active_run_id
                      ? "You’re previewing the saved draft. Your previous graph is still current."
                      : "Your feedback is saved. The current graph has not been replaced."
                    : "You can explore the updated graph. Some checks still need to finish."}
                </p>
                <ul className="bot-update-steps">
                  {Object.entries(feedbackSteps).map(([key, label]) => (
                    <li
                      key={key}
                      className={
                        update!.completed.includes(key) ? "complete" : "pending"
                      }
                    >
                      {update!.completed.includes(key) ? (
                        <Check size={14} />
                      ) : (
                        <Clock3 size={14} />
                      )}
                      <span>{label}</span>
                      <small>
                        {update!.completed.includes(key) ? "Done" : "Pending"}
                      </small>
                    </li>
                  ))}
                </ul>
                {!busy && update!.issue && (
                  <p className="bot-update-reason">
                    {update!.issue.reason} {update!.issue.next_step}
                  </p>
                )}
                {paused && !update!.can_resume && (
                  <p className="muted small">
                    A newer graph is current. Open it before making another
                    update.
                  </p>
                )}
              </div>
              <div className="bot-update-actions">
                <button
                  type="button"
                  className="primary-button"
                  disabled={
                    busy ||
                    (paused
                      ? !update!.can_resume
                      : map.run_id !== update!.active_run_id)
                  }
                  onClick={async () => {
                    setError("");
                    try {
                      await onResume();
                    } catch (error) {
                      setError(messageOf(error));
                    }
                  }}
                >
                  {paused ? "Resume update" : "Finish checks"}
                </button>
                <button
                  type="button"
                  className="quiet-button"
                  disabled={busy}
                  onClick={async () => {
                    setError("");
                    try {
                      await onKeepCurrent();
                    } catch (error) {
                      setError(messageOf(error));
                    }
                  }}
                >
                  {map.run_id !== update!.active_run_id
                    ? "Open current graph"
                    : paused
                      ? "Keep current graph"
                      : "Continue with this graph"}
                </button>
              </div>
              {paused && map.run_id !== update!.run_id && (
                <button
                  type="button"
                  className="text-button small"
                  disabled={busy}
                  onClick={onViewDraft}
                >
                  Preview revised topics
                </button>
              )}
              {error && (
                <p className="inline-error" role="alert">
                  {error}
                </p>
              )}
            </div>
          )}
          {!paused && (
            <form
              onSubmit={async (event) => {
                event.preventDefault();
                const submitted = text.trim();
                if (!submitted || busy || !editable || !ready) return;
                setError("");
                try {
                  await onSubmit(submitted);
                  setText("");
                } catch (error) {
                  setError(messageOf(error));
                }
              }}
            >
              <textarea
                aria-label="Feedback for the graph"
                placeholder="Tell us what to change…"
                value={text}
                maxLength={4000}
                onChange={(event) => setText(event.target.value)}
                disabled={busy || !ready || !editable}
              />
              {!editable && (
                <p className="muted small">
                  Open the active version to update this graph.
                </p>
              )}
              {error && (
                <p className="inline-error" role="alert">
                  {error}
                </p>
              )}
              <button
                className="primary-button"
                type="submit"
                disabled={!text.trim() || busy || !ready || !editable}
              >
                {busy ? (
                  <LoaderCircle size={15} className="spin" />
                ) : (
                  <Send size={15} />
                )}{" "}
                Update graph
              </button>
            </form>
          )}
        </section>
      ) : (
        <button
          className="feedback-launcher"
          aria-label="Open feedback assistant"
          onClick={() => setOpen(true)}
        >
          <MessageCircle size={20} /> Feedback
        </button>
      )}
    </div>
  );
}
