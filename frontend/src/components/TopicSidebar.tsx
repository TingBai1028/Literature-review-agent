import { Info } from "lucide-react";
import type { Cluster, Selection } from "../types";
export const colors = [
  "#86bda9",
  "#92bce4",
  "#b5a5df",
  "#dfad8d",
  "#e1c16b",
  "#cb9aa8",
];
export const topicColor = (c: Cluster, i: number) =>
  c.kind === "main"
    ? "#28584b"
    : c.kind === "foundation"
      ? "#9a7438"
      : colors[i % colors.length];
export const roleName = (c?: Cluster) =>
  c?.kind === "main"
    ? "Main cluster"
    : c?.kind === "foundation"
      ? "Foundation cluster"
      : "Side cluster";
export function TopicSidebar({
  clusters,
  selection,
  onSelect,
  mobileOpen,
}: {
  clusters: Cluster[];
  selection: Selection | null;
  onSelect: (s: Selection) => void;
  mobileOpen: boolean;
}) {
  return (
    <aside
      className={`topic-sidebar ${mobileOpen ? "mobile-open" : ""}`}
      aria-label="Topic navigation"
    >
      <div className="sidebar-heading">
        <h2>Topics</h2>
      </div>
      <nav className="topic-list">
        {clusters.map((c, index) => {
          const selected =
            selection?.type === "cluster"
              ? selection.id === c.id
              : selection?.type === "paper" &&
                c.paper_ids.includes(selection.id);
          return (
            <button
              key={c.id}
              className={`topic-row ${selected ? "selected" : ""}`}
              onClick={() => onSelect({ type: "cluster", id: c.id })}
              title={c.label}
              aria-pressed={selected}
            >
              <span
                className="topic-dot"
                style={{ background: topicColor(c, index) }}
              />
              <span className="topic-name">
                {c.kind === "main" || c.kind === "foundation"
                  ? `${roleName(c)} · `
                  : ""}
                {c.label.replace(/^Unclustered:\s*/, "")}
              </span>
              <span className="topic-count">{c.paper_ids.length}</span>
            </button>
          );
        })}
        {!clusters.length && <p className="muted small">No topics yet.</p>}
      </nav>
      <div className="sidebar-note">
        <Info size={16} />
        <span>Hypotheses still need human review</span>
      </div>
    </aside>
  );
}
