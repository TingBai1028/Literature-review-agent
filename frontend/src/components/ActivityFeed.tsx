import { useEffect, useRef } from "react";
import { LoaderCircle } from "lucide-react";
import { agentNames, isSetback, type RunEvent } from "../events";

/** Spec A3: each event's message in plain text, newest at the bottom, with the agent at work named. */
export function ActivityFeed({
  events,
  title,
  onShowAll,
  inline = false,
}: {
  events: RunEvent[];
  title: string;
  onShowAll?: () => void;
  inline?: boolean; // inside a dialog instead of floating over the map
}) {
  const end = useRef<HTMLLIElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "nearest" });
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
  return (
    <aside
      className={inline ? "activity-feed inline" : "activity-feed"}
      aria-live="polite"
      aria-label="运行动态"
    >
      <header>
        <LoaderCircle size={14} className="spin" />
        <strong>{title}</strong>
        {working && <span>· {agentNames[working] ?? working}正在工作</span>}
      </header>
      {fetched && (
        <p className="feed-counter">
          已获取 {fetched.papers_fetched} / {fetched.target} 篇
        </p>
      )}
      <ol>
        {shown.slice(-8).map((e) => (
          <li key={e.seq} className={isSetback(e) ? "setback" : e.phase}>
            <b>{agentNames[e.agent] ?? e.agent}</b> {e.message}
          </li>
        ))}
        <li ref={end} className="feed-end" aria-hidden />
      </ol>
      {onShowAll && (
        <button className="text-button small" onClick={onShowAll}>
          查看完整推理过程（{events.length} 步）
        </button>
      )}
    </aside>
  );
}
