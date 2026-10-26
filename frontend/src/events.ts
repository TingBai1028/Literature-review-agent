// Live progress events (docs/events.md): one stream for the map animation, the activity feed and the reasoning
// panel (specs A1-A4, B3-B5). The client picks the run ID, subscribes, then starts the run with that ID.
import { useEffect, useState } from "react";
import { prefix, request } from "./api";
import type { Cluster, Connection, Gap, MapResult, Paper } from "./types";
import type { Neighbor } from "./layout";

export interface RunEvent {
  run_id: string;
  seq: number;
  ts: string | null;
  agent: string;
  phase: "start" | "step" | "partial_result" | "done" | "error";
  message: string;
  payload: any;
  step: string;
  step_kind: "code" | "llm" | "human" | null;
  decision: string;
  result: unknown;
  next: string;
  why: string;
  terminal: boolean;
}

/** Same shape as the server's run IDs (YYYYMMDD-HHMMSS-xxxxxx), so files sort the same way. */
export function newRunId() {
  const t = new Date().toISOString().replace(/[-:]/g, "").replace("T", "-");
  return `${t.slice(0, 15)}-${crypto.randomUUID().replaceAll("-", "").slice(0, 6)}`;
}

/** Follows a run's events until its terminal event; the stream is closed then, so the browser never re-subscribes. */
export function useRunEvents(runId: string | null) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  useEffect(() => {
    setEvents([]);
    if (!runId) return;
    const source = new EventSource(`${prefix}/runs/${runId}/events`);
    source.onmessage = (m) => {
      const event = JSON.parse(m.data) as RunEvent;
      setEvents((old) =>
        old.some((e) => e.seq === event.seq) ? old : [...old, event],
      );
      if (event.terminal) source.close();
    };
    return () => source.close();
  }, [runId]);
  return events;
}

export const fetchLog = (runId: string, signal?: AbortSignal) =>
  request<{ events: RunEvent[] }>(`/runs/${runId}/log`, { signal }).then(
    (r) => r.events,
  );

export const agentNames: Record<string, string> = {
  orchestrator: "Orchestrator",
  planner: "Planner",
  retriever: "Retriever",
  clusterer: "Clusterer",
  connection_finder: "Connection finder",
  gap_finder: "Gap finder",
  grader: "Grader",
  review_agent: "Review agent",
  human: "Human review",
  zetaris: "Paper store",
  meterless_world_model: "World model",
};

/** Critiques, retries, fallbacks and errors are shown, not hidden (spec B5). */
export const isSetback = (e: RunEvent) =>
  e.phase === "error" ||
  ["rejected", "error", "fail"].some((w) => e.decision.includes(w)) ||
  /fallback|rewrite|repair|retry|redo|generic|relaxed/i.test(
    `${e.step} ${e.decision} ${e.message}`,
  );

const latest = (events: RunEvent[], agent: string, step?: string) =>
  [...events]
    .reverse()
    .find(
      (e) =>
        e.agent === agent &&
        e.phase === "partial_result" &&
        (!step || e.step === step),
    );

/** A map being built (spec A2): papers first, then clusters as soon as they are grouped, then their names. */
export function buildingMap(
  runId: string,
  question: string,
  papers: Paper[],
  events: RunEvent[],
  sample: boolean,
): { map: MapResult; neighbors: Neighbor[] } {
  const grouped = latest(events, "clusterer", "group papers");
  const named = latest(events, "clusterer", "name clusters");
  const source = (named ?? grouped)?.payload?.clusters as
    (Cluster & { role_reason?: string })[] | undefined;
  const clusters: Cluster[] = source
    ? source.map((c) => ({
        id: c.id,
        kind: c.kind,
        label: c.label ?? "Naming…",
        paper_ids: c.paper_ids,
        rationale: "",
        role_reason: c.role_reason ?? null,
      }))
    : [
        {
          id: "PENDING",
          kind: "side",
          label: "Grouping…",
          paper_ids: papers.map((p) => p.id),
          rationale: "",
        },
      ];
  // Ungrouped papers get their own layout key, so grouping can move them while the grouped layout matches the
  // saved map exactly (same seed, same neighbours) and nothing jumps when the run finishes.
  const map = {
    run_id: runId,
    root_run_id: source ? runId : `${runId}:pending`,
    question,
    sample_mode: sample,
    clusters,
    connections: [],
    gaps: [],
    warnings: [],
    version_token: "",
  } as unknown as MapResult;
  return { map, neighbors: grouped?.payload?.neighbors ?? [] };
}

/** An analysis or refresh in progress: the base map plus the edges and gaps accepted so far (specs A2, A4, E2). */
export function overlay(base: MapResult, events: RunEvent[]): MapResult {
  const edges = events
    .filter(
      (e) => e.agent === "connection_finder" && e.phase === "partial_result",
    )
    .flatMap((e) => e.payload?.edges ?? []);
  const gaps = events
    .filter((e) => e.agent === "gap_finder" && e.phase === "partial_result")
    .flatMap((e) => e.payload?.gaps ?? []);
  const connections: Connection[] = edges.map((e: any) => ({
    id: e.id,
    kind: "within_cluster",
    paper_ids: [e.source, e.target],
    cluster_ids: [],
    description: e.reason_short ?? "",
    reason_short: e.reason_short,
    relation: e.relation,
    evidence: [],
  }));
  const liveGaps: Gap[] = gaps.map((g: any) => ({
    id: g.id,
    cluster_id: g.cluster_id,
    between_paper_ids: g.paper_ids,
    description: g.description,
    why_it_matters: "",
    evidence: [],
    label: g.label,
    gap_type: g.paper_ids.length === 1 ? "explicit" : "inferred",
  }));
  const known = new Set(base.connections.map((c) => c.id));
  const knownGaps = new Set(base.gaps.map((g) => g.id));
  return {
    ...base,
    connections: [
      ...base.connections,
      ...connections.filter((c) => !known.has(c.id)),
    ],
    gaps: [...base.gaps, ...liveGaps.filter((g) => !knownGaps.has(g.id))],
  };
}
