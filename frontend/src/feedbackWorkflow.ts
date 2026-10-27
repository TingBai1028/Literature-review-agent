import { ApiError, messageOf } from "./api";

export const feedbackSteps: Record<string, string> = {
  clusters: "Topics revised",
  clusters_grade: "Topics checked",
  connections: "Connection graph",
  connections_grade: "Connections reviewed",
  gaps: "Gap graph",
  gaps_grade: "Gaps reviewed",
};

export function feedbackError(error: unknown): string {
  const raw = messageOf(error);
  if (
    /key_missing|api key|not configured|authentication|unauthorized/i.test(raw)
  )
    return "The checking service is not configured. Your feedback is still here. Try again after the service connection is restored.";
  if (/insufficient|credit|balance|payment required/i.test(raw))
    return "The model service has no remaining credit. Your feedback is still here. Try again after service credit is restored.";
  if (error instanceof ApiError && error.status === 409) return raw;
  if (error instanceof Error && error.name === "TimeoutError")
    return "The service is taking too long. Your feedback is still here. Please wait before retrying; the update may still be running.";
  return "The graph could not be updated. Your feedback is still here. Please try again when the service is available.";
}
