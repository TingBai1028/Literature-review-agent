import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

// The topics panel (left) and the details panel (right) can be folded away and resized on desktop. The layout is a
// per-viewer convenience kept in this browser; anything else (a private window, blocked storage) gets the defaults.

type Side = "left" | "right";
type Panel = { width: number | null; open: boolean }; // width null: the stylesheet's default
export type Panels = Record<Side, Panel>;

const KEY = "litagent.panels";
const LIMITS: Record<Side, [number, number]> = { left: [200, 520], right: [280, 720] };
const MIN_MAP = 420; // the map keeps at least this much width
const STEP = 24; // arrow-key resize step
const DEFAULTS: Panels = { left: { width: null, open: true }, right: { width: null, open: true } };

function load(): Panels {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) ?? "null");
    if (saved?.left && saved?.right) return saved;
  } catch {
    /* defaults */
  }
  return DEFAULTS;
}

export function usePanels() {
  const [panels, setPanels] = useState<Panels>(load);
  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(panels));
    } catch {
      /* layout is not saved; nothing else depends on it */
    }
  }, [panels]);
  const set = (side: Side, change: Partial<Panel>) =>
    setPanels((p) => ({ ...p, [side]: { ...p[side], ...change } }));
  const column = ({ width, open }: Panel) => (!open ? "0px" : width != null ? `${width}px` : undefined);
  const style = Object.fromEntries(
    [
      ["--left-col", column(panels.left)],
      ["--right-col", column(panels.right)],
    ].filter(([, v]) => v),
  ) as CSSProperties;
  const className = `${panels.left.open ? "" : " left-folded"}${panels.right.open ? "" : " right-folded"}`;
  return { panels, set, style, className };
}

/** The divider between a side panel and the map: drag (or arrow keys) to resize, double-click for the default
 * width, and a chevron button to fold the panel away or bring it back. */
export function PanelHandle({
  side,
  panels,
  set,
}: {
  side: Side;
  panels: Panels;
  set: (side: Side, change: Partial<Panel>) => void;
}) {
  const drag = useRef<{ x: number; width: number; max: number } | null>(null);
  const { width, open } = panels[side];
  const label = side === "left" ? "topics panel" : "details panel";
  const [low, high] = LIMITS[side];
  const measure = (handle: Element) => {
    const grid = handle.closest(".workspace-grid")!;
    const panel = grid.querySelector(side === "left" ? ".topic-sidebar" : ".inspector");
    const other = grid.querySelector(side === "left" ? ".inspector" : ".topic-sidebar");
    const current = panel?.getBoundingClientRect().width ?? low;
    const max = Math.min(high, grid.clientWidth - (other?.getBoundingClientRect().width ?? 0) - MIN_MAP);
    return { current, max: Math.max(low, max) };
  };
  const clamp = (w: number, max: number) => Math.round(Math.min(Math.max(w, low), max));
  const start = (e: PointerEvent<HTMLDivElement>) => {
    if (!open) return;
    const { current, max } = measure(e.currentTarget);
    drag.current = { x: e.clientX, width: current, max };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const move = (e: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    const dx = e.clientX - drag.current.x;
    set(side, { width: clamp(drag.current.width + (side === "left" ? dx : -dx), drag.current.max) });
  };
  const key = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const { current, max } = measure(e.currentTarget);
    const wider = (e.key === "ArrowRight") === (side === "left");
    set(side, { width: clamp(current + (wider ? STEP : -STEP), max) });
  };
  const toggle = () => set(side, { open: !open });
  return (
    <div className={`panel-handle ${side}${open ? "" : " folded"}`}>
      {open && (
        <div
          className="panel-resizer"
          role="separator"
          aria-orientation="vertical"
          aria-label={`Resize the ${label}`}
          aria-valuemin={low}
          aria-valuemax={high}
          aria-valuenow={width ?? undefined}
          tabIndex={0}
          title="Drag to resize; double-click for the default width"
          onPointerDown={start}
          onPointerMove={move}
          onPointerUp={() => (drag.current = null)}
          onPointerCancel={() => (drag.current = null)}
          onDoubleClick={() => set(side, { width: null })}
          onKeyDown={key}
        />
      )}
      <button
        className="panel-fold"
        aria-label={open ? `Fold the ${label}` : `Show the ${label}`}
        aria-expanded={open}
        title={open ? `Fold the ${label}` : `Show the ${label}`}
        onClick={toggle}
      >
        {(side === "left") === open ? <ChevronLeft size={14} /> : <ChevronRight size={14} />}
      </button>
    </div>
  );
}
