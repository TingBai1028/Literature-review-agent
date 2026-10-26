import { useEffect, useMemo, useRef, useState, type PointerEvent } from "react";
import { Minus, Plus, RotateCcw } from "lucide-react";
import { request } from "../api";
import { blobPath, forceLayout, yearShade, type Neighbor } from "../layout";
import type { Filter, MapResult, Paper, Selection } from "../types";
import { topicColor } from "./TopicSidebar";
function wrap(text: string) {
  const words = text.replace(/^Unclustered:\s*/, "").split(/\s+/);
  const lines = [""];
  for (const w of words) {
    if (lines.at(-1)!.length + w.length > 18 && lines.length < 2) lines.push(w);
    else lines[lines.length - 1] += (lines.at(-1) ? " " : "") + w;
  }
  return lines.map((line) =>
    line.length > 20 ? line.slice(0, 18) + "…" : line,
  );
}
export function LiteratureGraph({
  map,
  papers,
  selection,
  onSelect,
  filter,
  onFilter,
  search,
  onReview,
  neighbors: supplied,
}: {
  map: MapResult;
  papers: Paper[];
  selection: Selection | null;
  onSelect: (s: Selection) => void;
  filter: Filter;
  onFilter: (f: Filter) => void;
  search: string;
  onReview: () => void;
  /** A live map passes the neighbours from its events instead of fetching a saved version's. */
  neighbors?: Neighbor[];
}) {
  const [view, setView] = useState({ x: 0, y: 0, scale: 1 });
  const drag = useRef<{ x: number; y: number; vx: number; vy: number } | null>(
    null,
  );
  const svg = useRef<SVGSVGElement>(null);
  // Spec G: positions come only from a seeded force simulation over paper similarity (no grid slots).
  const [fetched, setNeighbors] = useState<Neighbor[] | null>(null);
  const neighbors = supplied ?? fetched;
  useEffect(() => {
    if (supplied) return;
    const abort = new AbortController();
    setNeighbors(null);
    request<{ pairs: Neighbor[] }>(`/cluster/${map.run_id}/neighbors`, {
      signal: abort.signal,
    })
      .then((r) => !abort.signal.aborted && setNeighbors(r.pairs))
      .catch(() => !abort.signal.aborted && setNeighbors([]));
    return () => abort.abort();
  }, [map.run_id, supplied]);
  const layout = useMemo(() => {
    if (neighbors === null) return null;
    const positions = forceLayout(
      map.root_run_id || map.run_id,
      map.clusters,
      papers,
      neighbors,
      map.connections,
    );
    const years = papers.map((p) => p.year).filter((y): y is number => !!y);
    const [minYear, maxYear] = [Math.min(...years), Math.max(...years)];
    const groups = map.clusters.map((c, i) => {
      const points = c.paper_ids.map((id) => positions.get(id)!);
      const main = c.kind === "main";
      return {
        c,
        main,
        color: topicColor(c, i),
        x: points.reduce((s, p) => s + p.x, 0) / points.length,
        top: Math.min(...points.map((p) => p.y - p.r)),
        path: blobPath(points, main ? 26 : 18),
        labelled: true,
      };
    });
    // Greedy label placement, main first: a label that would overlap one already placed is hidden until its
    // cluster (or one of its papers) is selected, so names never pile up on top of each other.
    const placed: { x0: number; x1: number; y0: number; y1: number }[] = [];
    for (const g of [...groups].sort(
      (a, b) => Number(b.main) - Number(a.main),
    )) {
      const half = Math.min(g.c.label.length, 22) * 3.6 + 8;
      const y = g.top - (g.main ? 34 : 26);
      const box = { x0: g.x - half, x1: g.x + half, y0: y - 14, y1: y + 18 };
      g.labelled = !placed.some(
        (b) => box.x0 < b.x1 && b.x0 < box.x1 && box.y0 < b.y1 && b.y0 < box.y1,
      );
      if (g.labelled) placed.push(box);
    }
    const shade = (id: string, color: string) =>
      yearShade(color, papers.find((p) => p.id === id)?.year, minYear, maxYear);
    return { groups, positions, shade };
  }, [
    map.run_id,
    map.root_run_id,
    map.clusters,
    map.connections,
    papers,
    neighbors,
  ]);
  const paperMap = useMemo(
    () => new Map(papers.map((p) => [p.id, p])),
    [papers],
  );
  const matches = (id: string) =>
    !search ||
    (paperMap.get(id)?.title.toLowerCase().includes(search.toLowerCase()) ??
      false) ||
    map.clusters
      .find((c) => c.paper_ids.includes(id))
      ?.label.toLowerCase()
      .includes(search.toLowerCase());
  const point = (id: string) => layout?.positions.get(id);
  const selectedGroup = map.clusters.find((c) =>
    selection?.type === "cluster"
      ? selection.id === c.id
      : selection?.type === "paper" && c.paper_ids.includes(selection.id),
  );
  // Edges link papers only (spec D1): paper-to-cluster similarity hints stay in the inspector, not on the map.
  const [hovered, setHovered] = useState<string | null>(null);
  const hoveredEdge = map.connections.find((c) => c.id === hovered);
  const edgeEnter = (event: React.KeyboardEvent, s: Selection) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect(s);
    }
  };
  const activeIds =
    filter === "connections"
      ? new Set(map.connections.flatMap((c) => c.paper_ids))
      : filter === "gaps"
        ? new Set(map.gaps.flatMap((g) => g.between_paper_ids))
        : null;
  const panStart = (e: PointerEvent<SVGSVGElement>) => {
    if ((e.target as Element).closest("[data-interactive]")) return;
    drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const panMove = (e: PointerEvent<SVGSVGElement>) => {
    if (drag.current && svg.current) {
      const ratio = 1000 / svg.current.getBoundingClientRect().width;
      setView((v) => ({
        ...v,
        x: drag.current!.vx + (e.clientX - drag.current!.x) * ratio,
        y: drag.current!.vy + (e.clientY - drag.current!.y) * ratio,
      }));
    }
  };
  const noFindings =
    (filter === "gaps" && !map.gaps.length) ||
    (filter === "connections" && !map.connections.length);
  return (
    <section className="graph-panel" aria-label="交互论文地图">
      <div className="graph-toolbar">
        <div className="segmented" aria-label="地图筛选">
          {(
            [
              ["all", "全部"],
              ["main_side", "主簇与侧簇"],
              ["connections", "图 1 · 关联"],
              ["gaps", "图 2 · 研究空白"],
            ] as [Filter, string][]
          ).map(([key, label]) => (
            <button
              key={key}
              aria-pressed={filter === key}
              className={filter === key ? "active" : ""}
              onClick={() => onFilter(key)}
            >
              {label}
            </button>
          ))}
        </div>
        <button
          className="quiet-button reset"
          onClick={() => setView({ x: 0, y: 0, scale: 1 })}
        >
          <RotateCcw size={15} />
          重置视图
        </button>
      </div>
      {!noFindings && (
        <div className="graph-mobile-caption">
          <span>{selectedGroup?.label ?? "点选主题或论文查看原文"}</span>
          <small>可拖动地图 · 使用＋放大查看</small>
        </div>
      )}
      <div className="graph-canvas">
        {noFindings ? (
          <div className="graph-empty">
            <h2>
              {filter === "gaps"
                ? map.analysis?.pending_stages.includes("gaps")
                  ? "图 2（研究空白）尚未生成"
                  : "暂无通过核验的研究假设"
                : "暂无通过核验的关联"}
            </h2>
            <p>当前版本保留了核验结果与弃权记录。</p>
            <button className="secondary-button" onClick={onReview}>
              查看候选验收
            </button>
          </div>
        ) : !layout ? (
          <div className="graph-empty">
            <p>正在按相似度排布论文…</p>
          </div>
        ) : (
          <svg
            ref={svg}
            viewBox="0 0 1000 790"
            className="map-svg"
            aria-label={`论文地图，${papers.length} 篇论文`}
            onPointerDown={panStart}
            onPointerMove={panMove}
            onPointerUp={() => {
              drag.current = null;
            }}
            onPointerCancel={() => {
              drag.current = null;
            }}
          >
            <g
              transform={`translate(${500 + view.x},${380 + view.y}) scale(${view.scale}) translate(-500,-380)`}
            >
              {layout.groups.map(
                ({ c, main, x, top, path, color, labelled }) => {
                  const dim =
                    activeIds && !c.paper_ids.some((id) => activeIds.has(id));
                  const selected =
                    selection?.type === "cluster" && selection.id === c.id;
                  return (
                    <g key={c.id} opacity={dim ? 0.14 : 1}>
                      <path
                        data-interactive="true"
                        role="button"
                        tabIndex={0}
                        aria-label={`主题：${c.label}`}
                        d={path}
                        fill={color}
                        fillOpacity={main ? 0.2 : 0.1}
                        stroke={color}
                        strokeOpacity={main ? 0.9 : selected ? 0.7 : 0.25}
                        strokeWidth={main ? 2.2 : 1.2}
                        onClick={() => onSelect({ type: "cluster", id: c.id })}
                        onKeyDown={(e) =>
                          edgeEnter(e, { type: "cluster", id: c.id })
                        }
                      />
                      {(labelled ||
                        selected ||
                        (selection?.type === "paper" &&
                          c.paper_ids.includes(selection.id))) && (
                        <text
                          x={x}
                          y={top - (main ? 34 : 26)}
                          textAnchor="middle"
                          className={
                            main ? "main-graph-label" : "topic-graph-label"
                          }
                        >
                          {(main
                            ? [
                                "主簇 · " +
                                  wrap(
                                    c.label.replace(/^Sample main:\s*/, ""),
                                  )[0],
                              ]
                            : map.clusters.length > 19 &&
                                !selected &&
                                !(
                                  selection?.type === "paper" &&
                                  c.paper_ids.includes(selection.id)
                                )
                              ? [`${c.paper_ids.length} 篇`]
                              : wrap(c.label)
                          ).map((line, j) => (
                            <tspan key={j} x={x} dy={j ? 16 : 0}>
                              {line}
                            </tspan>
                          ))}
                        </text>
                      )}
                    </g>
                  );
                },
              )}
              {filter !== "gaps" &&
                map.connections.map((c) => {
                  const a = point(c.paper_ids[0]),
                    b = point(c.paper_ids[1]);
                  if (
                    !a ||
                    !b ||
                    (filter === "main_side" && c.kind !== "between_clusters")
                  )
                    return null;
                  return (
                    <g key={c.id}>
                      <line
                        className="edge-line"
                        pathLength={1}
                        x1={a.x}
                        y1={a.y}
                        x2={b.x}
                        y2={b.y}
                        stroke="#28584b"
                        strokeWidth={2.5}
                      />
                      <line
                        data-interactive="true"
                        role="button"
                        tabIndex={0}
                        aria-label={`查看关联：${c.reason_short ?? c.description}`}
                        x1={a.x}
                        y1={a.y}
                        x2={b.x}
                        y2={b.y}
                        stroke="transparent"
                        strokeWidth={14}
                        onMouseEnter={() => setHovered(c.id)}
                        onMouseLeave={() => setHovered(null)}
                        onFocus={() => setHovered(c.id)}
                        onBlur={() => setHovered(null)}
                        onClick={() =>
                          onSelect({ type: "connection", id: c.id })
                        }
                        onKeyDown={(e) =>
                          edgeEnter(e, { type: "connection", id: c.id })
                        }
                      />
                    </g>
                  );
                })}
              {(filter === "all" ||
                filter === "gaps" ||
                filter === "main_side") &&
                map.gaps.map((g) => {
                  const a = point(g.between_paper_ids[0]),
                    b = g.between_paper_ids[1]
                      ? point(g.between_paper_ids[1])
                      : undefined;
                  // An explicit gap is stated by one paper: a marker beside that paper, no line.
                  const m =
                    a && b
                      ? { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }
                      : a && g.gap_type === "explicit"
                        ? { x: a.x + 14, y: a.y - 14 }
                        : null;
                  return m ? (
                    <g
                      key={g.id}
                      className="gap-marker"
                      data-interactive="true"
                      role="button"
                      tabIndex={0}
                      aria-label={`查看研究假设：${g.description}`}
                      onClick={() => onSelect({ type: "gap", id: g.id })}
                      onKeyDown={(e) => edgeEnter(e, { type: "gap", id: g.id })}
                    >
                      {a && b && (
                        <line
                          x1={a.x}
                          y1={a.y}
                          x2={b.x}
                          y2={b.y}
                          stroke="#a86e3c"
                          strokeDasharray="3 4"
                          strokeWidth={2}
                        />
                      )}
                      <circle
                        cx={m.x}
                        cy={m.y}
                        r={11}
                        fill="#fff9ef"
                        stroke="#a86e3c"
                      />
                      <text
                        x={m.x}
                        y={m.y + 4}
                        textAnchor="middle"
                        fontSize={13}
                        fill="#82562e"
                      >
                        {g.gap_type === "explicit" ? "!" : "?"}
                      </text>
                    </g>
                  ) : null;
                })}
              {layout.groups.flatMap(({ c, color }) =>
                c.paper_ids.map((id) => {
                  const p = point(id)!;
                  const selected =
                    selection?.type === "paper" && selection.id === id;
                  const dim = !matches(id) || (activeIds && !activeIds.has(id));
                  return (
                    <g
                      key={id}
                      data-interactive="true"
                      role="button"
                      tabIndex={0}
                      className="paper-node"
                      style={{ transform: `translate(${p.x}px, ${p.y}px)` }}
                      aria-label={`论文：${paperMap.get(id)?.title ?? id}`}
                      opacity={dim ? 0.15 : 1}
                      onClick={() => onSelect({ type: "paper", id })}
                      onKeyDown={(e) => edgeEnter(e, { type: "paper", id })}
                    >
                      <title>{paperMap.get(id)?.title ?? id}</title>
                      {selected && (
                        <circle
                          r={p.r + 6}
                          fill="none"
                          stroke={color}
                          strokeWidth={1.5}
                          opacity={0.6}
                        />
                      )}
                      <circle
                        r={p.r}
                        fill={layout.shade(id, color)}
                        stroke={c.kind === "main" ? color : "white"}
                        strokeWidth={1.5}
                      />
                    </g>
                  );
                }),
              )}
              {hoveredEdge &&
                (() => {
                  const a = point(hoveredEdge.paper_ids[0]),
                    b = point(hoveredEdge.paper_ids[1]);
                  return a && b ? (
                    <foreignObject
                      x={(a.x + b.x) / 2 - 130}
                      y={(a.y + b.y) / 2 + 10}
                      width={260}
                      height={90}
                      pointerEvents="none"
                    >
                      <div className="edge-tooltip">
                        {hoveredEdge.reason_short ?? hoveredEdge.description}
                      </div>
                    </foreignObject>
                  ) : null;
                })()}
            </g>
          </svg>
        )}
      </div>
      <div className="graph-bottom">
        <div
          className="graph-legend"
          title="位置由论文相似度决定：越相似越靠近。节点越大引用越多，颜色越深越新；色块表示簇，主簇在中央并加粗描边。连线只连接论文：悬停看关联原因，点击看完整说明、依据和相似度。"
        >
          <span>
            <i style={{ background: "#28584b" }} />
            主簇
          </span>
          <span>
            <i style={{ background: "#9a7438" }} />
            基础簇
          </span>
          <span>
            <i style={{ background: "#d9e8e0" }} />
            侧簇
          </span>
          <span>
            <b className="legend-line" />
            关联
          </span>
          <span>
            <b className="legend-line dashed" />
            研究空白
          </span>
        </div>
        <div className="zoom-controls">
          <button
            aria-label="缩小地图"
            onClick={() =>
              setView((v) => ({ ...v, scale: Math.max(0.55, v.scale - 0.15) }))
            }
          >
            <Minus size={18} />
          </button>
          <button
            aria-label="放大地图"
            onClick={() =>
              setView((v) => ({ ...v, scale: Math.min(2.5, v.scale + 0.15) }))
            }
          >
            <Plus size={18} />
          </button>
        </div>
      </div>
    </section>
  );
}
