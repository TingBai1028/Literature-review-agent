import { useEffect, useId, useMemo, useRef, useState } from "react";
import { ArrowRight, BookOpen, Layers, Search, X } from "lucide-react";
import { searchMap } from "../search";
import type { Cluster, Paper, Selection } from "../types";

export function MapSearch({
  clusters,
  papers,
  disabled,
  onSelect,
}: {
  clusters: Cluster[];
  papers: Paper[];
  disabled: boolean;
  onSelect: (selection: Selection) => void;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const resultsId = useId();
  const visible = open && !!query.trim() && !disabled;
  useEffect(() => {
    if (!visible) return;
    const dismiss = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", dismiss);
    return () => document.removeEventListener("pointerdown", dismiss);
  }, [visible]);
  const results = useMemo(() => {
    const titles = searchMap([], papers, query);
    if (!titles.hasQuery) return { papers: [], clusters: [] };
    const topics = searchMap(clusters, [], query).clusterIds;
    return {
      papers: papers.filter((p) => titles.paperIds.has(p.id)),
      clusters: clusters.filter((c) => topics.has(c.id)),
    };
  }, [clusters, papers, query]);
  const owner = useMemo(
    () =>
      new Map(
        clusters.flatMap((c) =>
          c.paper_ids.map((id) => [id, c.label] as const),
        ),
      ),
    [clusters],
  );
  const close = () => {
    input.current?.focus();
    setOpen(false);
  };
  const pick = (selection: Selection) => {
    onSelect(selection);
    close();
  };
  return (
    <div
      className="header-search"
      ref={root}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape" && visible) {
          event.preventDefault();
          close();
        }
        if (
          event.key === "ArrowDown" &&
          visible &&
          event.target === input.current
        ) {
          const first =
            root.current?.querySelector<HTMLButtonElement>(".search-result");
          if (first) {
            event.preventDefault();
            first.focus();
          }
        }
      }}
    >
      <form
        className="search-field header-search-form"
        role="search"
        onSubmit={(event) => {
          event.preventDefault();
          if (!disabled) setOpen(true);
        }}
      >
        <Search size={18} aria-hidden="true" />
        <input
          ref={input}
          aria-label="Search papers or topics"
          placeholder="Search papers or topics…"
          aria-controls={visible ? resultsId : undefined}
          value={query}
          disabled={disabled}
          onFocus={() => {
            if (query.trim()) setOpen(true);
          }}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpen(true);
          }}
        />
        {!!query && (
          <button
            className="icon-button"
            type="button"
            aria-label="Clear search"
            disabled={disabled}
            onClick={() => {
              setQuery("");
              close();
            }}
          >
            <X size={16} />
          </button>
        )}
      </form>
      {visible && (
        <section
          className="search-popover"
          id={resultsId}
          aria-label="Search results"
        >
          <header className="search-results-heading">
            <strong>Search results</strong>
            <button
              className="icon-button"
              aria-label="Close search results"
              onClick={close}
            >
              <X size={18} />
            </button>
          </header>
          <div className="map-search-results">
            {results.papers.map((paper) => (
              <button
                className="search-result"
                key={paper.id}
                onClick={() => pick({ type: "paper", id: paper.id })}
              >
                <BookOpen size={18} />
                <span>
                  <strong>{paper.title}</strong>
                  <small>
                    Paper · {owner.get(paper.id) ?? "Unassigned topic"}
                  </small>
                </span>
                <ArrowRight size={16} />
              </button>
            ))}
            {results.clusters.map((cluster) => (
              <button
                className="search-result"
                key={cluster.id}
                onClick={() => pick({ type: "cluster", id: cluster.id })}
              >
                <Layers size={18} />
                <span>
                  <strong>{cluster.label}</strong>
                  <small>Topic · Open details</small>
                </span>
                <ArrowRight size={16} />
              </button>
            ))}
            {!results.papers.length && !results.clusters.length && (
              <p className="muted search-no-results" role="status">
                No matching papers or topics.
              </p>
            )}
          </div>
        </section>
      )}
    </div>
  );
}
