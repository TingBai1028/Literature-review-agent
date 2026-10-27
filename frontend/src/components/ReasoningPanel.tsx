import { useEffect, useMemo, useState } from "react";
import { messageOf } from "../api";
import { agentNames, fetchLog, isSetback, type RunEvent } from "../events";
import type { MapResult, Versions } from "../types";

const kindNames = { code: "Code", llm: "LLM", human: "Human" } as const;
const QUIET = new Set(["zetaris", "meterless_world_model"]);

/** Spec B4/B5: each agent's run log as plain sentences, setbacks highlighted, raw data behind a details toggle.
 * Covers the whole lineage of the open version: the map, Connection graph, Gap graph and any refresh or move. */
export function ReasoningPanel({
  map,
  versions,
  live,
}: {
  map: MapResult;
  versions: Versions;
  live: RunEvent[];
}) {
  const chain = useMemo(() => {
    const parent = new Map(
      versions.versions.map((v) => [v.run_id, v.parent_run_id]),
    );
    const ids: string[] = [];
    for (
      let id: string | null | undefined = map.run_id;
      id && !ids.includes(id);
      id = parent.get(id)
    )
      ids.unshift(id);
    return ids;
  }, [map.run_id, versions]);
  const [events, setEvents] = useState<RunEvent[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const abort = new AbortController();
    setEvents(null);
    Promise.all(chain.map((id) => fetchLog(id, abort.signal).catch(() => [])))
      .then((logs) => !abort.signal.aborted && setEvents(logs.flat()))
      .catch((e) => !abort.signal.aborted && setError(messageOf(e)));
    return () => abort.abort();
  }, [chain]);
  const all = [...(events ?? []), ...live];
  const agents = [...new Set(all.map((e) => e.agent))].filter(
    (a) => !QUIET.has(a) || all.some((e) => e.agent === a && isSetback(e)),
  );
  return (
    <main className="reasoning-panel">
      <header>
        <h2>Reasoning</h2>
        <p className="muted small">
          Every step of every agent: what it decided, why, and whether the step
          was code or an LLM. Corrections, retries and fallbacks are marked in
          orange.
        </p>
      </header>
      {!!map.warnings.length && (
        <details className="reasoning-warnings">
          <summary>Run warnings ({map.warnings.length})</summary>
          <ul>
            {map.warnings.map((warning, index) => (
              <li key={index}>{warning}</li>
            ))}
          </ul>
        </details>
      )}
      {error && <p className="inline-error">{error}</p>}
      {events === null && !live.length && (
        <p className="muted">Loading the run log…</p>
      )}
      {agents.map((agent) => {
        const steps = all.filter((e) => e.agent === agent);
        const setbacks = steps.filter(isSetback).length;
        const llm = steps.filter((e) => e.step_kind === "llm").length;
        return (
          <details key={agent} className="agent-log" open={setbacks > 0}>
            <summary>
              <strong>{agentNames[agent] ?? agent}</strong>
              <span className="muted small">
                {steps.length} steps · {llm} LLM calls
                {setbacks
                  ? ` · ${setbacks} corrections, retries or fallbacks`
                  : ""}
              </span>
            </summary>
            <AgentSteps steps={steps} />
          </details>
        );
      })}
    </main>
  );
}

function AgentSteps({ steps }: { steps: RunEvent[] }) {
  const [limit, setLimit] = useState(40);
  return (
    <ol className="agent-steps">
      {steps.slice(0, limit).map((e) => (
        <li
          key={`${e.run_id}-${e.seq}`}
          className={isSetback(e) ? "setback" : undefined}
        >
          <span className={`kind ${e.step_kind ?? "code"}`}>
            {kindNames[e.step_kind ?? "code"]}
          </span>
          {/* Messages are cut short for the feed; the panel has room for the whole reason. */}
          <span>
            {e.message.endsWith("...") && e.why
              ? `${e.step}: ${e.decision}. ${e.why}`
              : e.message}
          </span>
          <details className="raw">
            <summary>Details</summary>
            <pre>
              {JSON.stringify(
                {
                  step: e.step,
                  decision: e.decision,
                  next: e.next,
                  why: e.why,
                  result: e.result,
                  payload: e.payload,
                },
                null,
                2,
              )}
            </pre>
          </details>
        </li>
      ))}
      {steps.length > limit && (
        <li>
          <button
            className="text-button small"
            onClick={() => setLimit((n) => n + 100)}
          >
            Show more ({steps.length - limit} more steps)
          </button>
        </li>
      )}
    </ol>
  );
}
