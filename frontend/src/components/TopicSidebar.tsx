import { Search, Info, MoreHorizontal } from "lucide-react";
import { useMemo, useState } from "react";
import type { Cluster, Paper, Selection } from "../types";
import { searchMap } from "../search";
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
  c?.kind === "main" ? "Main cluster" : c?.kind === "foundation" ? "Foundation cluster" : "Side cluster";
export function TopicSidebar({
  clusters,
  papers,
  selection,
  onSelect,
  search,
  onSearch,
  mobileOpen,
}: {
  clusters: Cluster[];
  papers: Paper[];
  selection: Selection | null;
  onSelect: (s: Selection) => void;
  search: string;
  onSearch: (s: string) => void;
  mobileOpen: boolean;
}) {
  const [all, setAll] = useState(false);
  const { clusterIds, hasQuery } = useMemo(
    () => searchMap(clusters, papers, search),
    [clusters, papers, search],
  );
  const matches = clusters.filter((c) => clusterIds.has(c.id));
  const shown = all || hasQuery ? matches : matches.slice(0, 7);
  return (
    <aside
      className={`topic-sidebar ${mobileOpen ? "mobile-open" : ""}`}
      aria-label="Topic navigation"
    >
      <div className="sidebar-heading">
        <h2>Topics</h2>
      </div>
      <label className="search-field">
        <Search size={17} />
        <input
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          placeholder="Search papers or topics"
          aria-label="Search papers or topics"
        />
      </label>
      <nav className="topic-list">
        {shown.map((c) => {
          const index = clusters.indexOf(c);
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
        {!shown.length && <p className="muted small">No matching topics.</p>}
      </nav>
      {!hasQuery && matches.length > 7 && (
        <button className="show-topics" onClick={() => setAll((v) => !v)}>
          <MoreHorizontal size={20} />
          {all ? "Show fewer topics" : `Show all ${matches.length} topics`}
        </button>
      )}
      <div className="sidebar-note">
        <Info size={16} />
        <span>Hypotheses still need human review</span>
      </div>
    </aside>
  );
}
