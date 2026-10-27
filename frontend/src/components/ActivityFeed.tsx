import { useEffect, useRef } from "react";
import { ChevronDown, LoaderCircle } from "lucide-react";
import { agentNames, isSetback, type RunEvent } from "../events";

/** Spec A3: each event's message in plain text, newest at the bottom, with the agent at work named. */
export function ActivityFeed({
  events,
  title,
  inline = false,
  dock = false,
}: {
  events: RunEvent[];
  title: string;
  inline?: boolean; // inside a dialog
  dock?: boolean; // reserved space above the workspace, outside the paper inspector
}) {
  const list = useRef<HTMLOListElement>(null);
  useEffect(() => {
    // Scroll only the event list, without moving the reader's paper or the whole page.
    if (list.current) list.current.scrollTop = list.current.scrollHeight;
  }, [events.length]);
  const open = new Set<string>();
  for (const e of events) {
    if (e.phase === "start") open.add(e.agent);
    if (e.phase === "done" || e.phase === "error") open.delete(e.agent);
  }
  const working = [...open].filter((a) => a !== "orchestrator").at(-1);
  const fetched = [...events]
    .reverse()
    .find(
      (e) => e.agent === "retriever" && e.payload?.papers_fetched != null,
    )?.payload;
  const shown = events.filter((e) => e.phase !== "step" || isSetback(e));
  const heading = (
    <>
      <LoaderCircle size={14} className="spin" />
      <strong>{title}</strong>
      {working && <span>· {agentNames[working] ?? working} is working</span>}
    </>
  );
  const entries = (
    <>
      {fetched && (
        <p className="feed-counter">
          Fetched {fetched.papers_fetched} / {fetched.target} papers
        </p>
      )}
      <ol ref={list}>
        {shown.slice(-8).map((e) => (
          <li key={e.seq} className={isSetback(e) ? "setback" : e.phase}>
            <b>{agentNames[e.agent] ?? e.agent}</b> {e.message}
          </li>
        ))}
      </ol>
    </>
  );
  return (
    <aside
      className={`activity-feed${inline ? " inline" : ""}${dock ? " dock" : ""}`}
      aria-live="polite"
      aria-label="Run activity"
    >
      {dock ? (
        <details onToggle={(event) => {
          if (event.currentTarget.open && list.current) list.current.scrollTop = list.current.scrollHeight;
        }}>
          <summary aria-label="Build progress details">
            {heading}
            <span className="activity-latest">{shown.at(-1)?.message}</span>
            <span className="activity-toggle">Steps <ChevronDown size={14} /></span>
          </summary>
          {entries}
        </details>
      ) : (
        <>
          <header>{heading}</header>
          {entries}
        </>
      )}
    </aside>
  );
}
