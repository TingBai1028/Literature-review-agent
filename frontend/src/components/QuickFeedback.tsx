import { ThumbsDown, ThumbsUp } from "lucide-react";
import type { FeedbackTarget } from "../types";

export function QuickFeedback({
  target,
  vote,
  disabled,
  onVote,
}: {
  target: FeedbackTarget;
  vote?: "up" | "down";
  disabled: boolean;
  onVote: (target: FeedbackTarget, vote: "up" | "down") => void;
}) {
  return (
    <div
      className="quick-feedback"
      role="group"
      aria-label={`Feedback on this ${target.kind}`}
    >
      <button
        className="icon-button"
        aria-label={`Approve this ${target.kind}`}
        aria-pressed={vote === "up"}
        title="Looks good"
        disabled={disabled}
        onClick={() => onVote(target, "up")}
      >
        <ThumbsUp size={19} />
      </button>
      <button
        className="icon-button"
        aria-label={`Regenerate this ${target.kind}`}
        aria-pressed={vote === "down"}
        title="Needs improvement — regenerate the graph"
        disabled={disabled}
        onClick={() => onVote(target, "down")}
      >
        <ThumbsDown size={19} />
      </button>
    </div>
  );
}
