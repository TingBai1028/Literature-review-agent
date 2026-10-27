// Force-directed paper layout (spec G), in the style of Connected Papers: similar papers settle near each other,
// clusters hold together as soft hulls, and the main cluster sits in the centre. There are no grid slots: positions
// come only from the simulation. The layout is seeded by the map's lineage, and positions are cached per lineage, so
// Connection graph / Gap graph and refreshed versions keep every surviving paper where it was (specs E3, G4).
import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import type { Cluster, Connection, Paper } from "./types";

export interface Neighbor {
  source: string;
  target: string;
  similarity: number;
}
export interface Placed {
  x: number;
  y: number;
  r: number;
  cluster: string;
}
interface Node extends SimulationNodeDatum {
  id: string;
  r: number;
  cluster: string;
  main: boolean;
}
type Link = SimulationLinkDatum<Node> & { similarity: number };

const WIDTH = 1000,
  HEIGHT = 790,
  CENTER = { x: 500, y: 380 },
  STORAGE = "litmap-layout:";
const COHESION = 0.25; // pull towards the cluster's centroid per tick (times alpha)
const cache = new Map<string, Map<string, { x: number; y: number }>>();

function seeded(text: string) {
  let h = 2166136261;
  for (const ch of text) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
  return () => {
    h = Math.imul(h ^ (h >>> 15), 2246822507);
    h = Math.imul(h ^ (h >>> 13), 3266489909);
    return ((h ^= h >>> 16) >>> 0) / 4294967296;
  };
}

function remembered(root: string) {
  if (!cache.has(root)) {
    const positions = new Map<string, { x: number; y: number }>();
    try {
      const saved = localStorage.getItem(STORAGE + root);
      if (saved)
        for (const [id, p] of Object.entries(
          JSON.parse(saved) as Record<string, { x: number; y: number }>,
        ))
          positions.set(id, p);
    } catch {
      /* Storage may be unavailable; the seeded layout is still deterministic. */
    }
    cache.set(root, positions);
  }
  return cache.get(root)!;
}

/** Node radius from the citation count, log-scaled; main papers are a little larger. */
export const radius = (paper: Paper | undefined, main: boolean) =>
  5 + 2.4 * Math.log10(1 + (paper?.citation_count ?? 0)) + (main ? 3 : 0);

export function forceLayout(
  root: string,
  clusters: Cluster[],
  papers: Paper[],
  neighbors: Neighbor[],
  connections: Connection[],
): Map<string, Placed> {
  const byId = new Map(papers.map((p) => [p.id, p]));
  const memory = remembered(root);
  const random = seeded(root);
  const owner = new Map<string, Cluster>();
  clusters.forEach((c) => c.paper_ids.forEach((id) => owner.set(id, c)));
  // Initial anchors on a ring, main in the centre; only used for papers with no remembered position.
  const others = clusters.filter((c) => c.kind !== "main");
  const anchor = new Map<string, { x: number; y: number }>();
  clusters.forEach((c) => {
    const k = others.indexOf(c);
    const angle = (k / Math.max(others.length, 1)) * 2 * Math.PI;
    anchor.set(
      c.id,
      c.kind === "main"
        ? CENTER
        : {
            x: CENTER.x + 300 * Math.cos(angle),
            y: CENTER.y + 230 * Math.sin(angle),
          },
    );
  });
  const nodes: Node[] = [...owner.entries()].map(([id, c]) => {
    const known = memory.get(id);
    const a = anchor.get(c.id)!;
    const main = c.kind === "main";
    return {
      id,
      cluster: c.id,
      main,
      r: radius(byId.get(id), main),
      x: known?.x ?? a.x + (random() - 0.5) * 60,
      y: known?.y ?? a.y + (random() - 0.5) * 60,
      // Remembered papers stay put; only new ones (e.g. swapped in by refresh) are placed.
      fx: known?.x,
      fy: known?.y,
    };
  });
  const fresh = nodes.some((n) => n.fx === undefined);
  if (fresh) {
    const index = new Set(nodes.map((n) => n.id));
    const links: Link[] = [
      ...neighbors,
      ...connections.map((c) => ({
        source: c.paper_ids[0],
        target: c.paper_ids[1],
        similarity: c.similarity ?? 0.6,
      })),
    ]
      .filter((l) => index.has(l.source) && index.has(l.target))
      .map((l) => ({ ...l }));
    const crosses = (l: Link) =>
      (l.source as Node).cluster !== (l.target as Node).cluster;
    const centroid = new Map<string, { x: number; y: number }>();
    const cohesion = (alpha: number) => {
      // A weak pull towards each cluster's current centroid keeps clusters together without boxing them in.
      centroid.clear();
      const sums = new Map<string, { x: number; y: number; n: number }>();
      for (const n of nodes) {
        const s = sums.get(n.cluster) ?? { x: 0, y: 0, n: 0 };
        s.x += n.x!;
        s.y += n.y!;
        s.n += 1;
        sums.set(n.cluster, s);
      }
      sums.forEach((s, id) => centroid.set(id, { x: s.x / s.n, y: s.y / s.n }));
      for (const n of nodes) {
        if (n.fx !== undefined) continue;
        const c = centroid.get(n.cluster)!;
        n.vx! += (c.x - n.x!) * COHESION * alpha;
        n.vy! += (c.y - n.y!) * COHESION * alpha;
      }
    };
    forceSimulation(nodes)
      .randomSource(random)
      .force(
        "link",
        forceLink<Node, Link>(links)
          .id((n) => n.id)
          .distance(
            (l) =>
              (30 + 220 * (1 - Math.max(0, Math.min(1, l.similarity)))) *
              (crosses(l) ? 1.6 : 1),
          )
          // Links across clusters still pull similar papers closer, but weakly, so clusters stay apart.
          .strength(
            (l) => Math.max(0.05, l.similarity) ** 2 * (crosses(l) ? 0.2 : 1),
          ),
      )
      .force("charge", forceManyBody<Node>().strength(-70))
      .force(
        "collide",
        forceCollide<Node>().radius((n) => n.r + 3),
      )
      .force("cohesion", cohesion)
      .force(
        "x",
        forceX<Node>(CENTER.x).strength((n) => (n.main ? 0.12 : 0.012)),
      )
      .force(
        "y",
        forceY<Node>(CENTER.y).strength((n) => (n.main ? 0.12 : 0.012)),
      )
      .stop()
      .tick(320);
    if (!memory.size) fit(nodes);
    nodes.forEach((n) => memory.set(n.id, { x: n.x!, y: n.y! }));
    try {
      localStorage.setItem(
        STORAGE + root,
        JSON.stringify(Object.fromEntries(memory)),
      );
    } catch {
      /* Per-viewer convenience only. */
    }
  }
  return new Map(
    nodes.map((n) => [n.id, { x: n.x!, y: n.y!, r: n.r, cluster: n.cluster }]),
  );
}

/** Scale the first layout of a lineage into the view; later layouts keep that frame so papers never jump. */
function fit(nodes: Node[]) {
  const xs = nodes.map((n) => n.x!),
    ys = nodes.map((n) => n.y!);
  const [x0, x1, y0, y1] = [
    Math.min(...xs),
    Math.max(...xs),
    Math.min(...ys),
    Math.max(...ys),
  ];
  const scale = Math.min(
    (WIDTH - 140) / Math.max(x1 - x0, 1),
    (HEIGHT - 170) / Math.max(y1 - y0, 1),
    3,
  );
  const cx = (x0 + x1) / 2,
    cy = (y0 + y1) / 2;
  for (const n of nodes) {
    n.x = CENTER.x + (n.x! - cx) * scale;
    n.y = CENTER.y + (n.y! - cy) * scale;
  }
}

type Point = { x: number; y: number };

function convexHull(points: Point[]): Point[] {
  const sorted = [...points].sort((a, b) => a.x - b.x || a.y - b.y);
  const cross = (o: Point, a: Point, b: Point) =>
    (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
  const half = (list: Point[]) => {
    const out: Point[] = [];
    for (const p of list) {
      while (
        out.length >= 2 &&
        cross(out[out.length - 2], out[out.length - 1], p) <= 0
      )
        out.pop();
      out.push(p);
    }
    return out.slice(0, -1);
  };
  return [...half(sorted), ...half([...sorted].reverse())];
}

/** A soft blob around a cluster's papers (spec G3): the convex hull pushed out by `pad`, drawn as one smooth closed
 * curve through the midpoints of its edges, so it reads as an organic shape rather than a box. */
export function blobPath(points: Point[], pad: number) {
  if (points.length === 1) {
    const p = points[0];
    return `M${p.x - pad},${p.y}a${pad},${pad} 0 1,0 ${pad * 2},0a${pad},${pad} 0 1,0 ${-pad * 2},0Z`;
  }
  const hull = convexHull(points);
  let ring: Point[];
  if (hull.length < 3) {
    // Two papers (or a straight line of them): a capsule around the segment.
    const [a, b] =
      hull.length === 2 ? hull : [points[0], points[points.length - 1]];
    const len = Math.hypot(b.x - a.x, b.y - a.y) || 1;
    const d = { x: ((b.x - a.x) / len) * pad, y: ((b.y - a.y) / len) * pad };
    const n = { x: -d.y, y: d.x };
    ring = [
      { x: a.x - d.x, y: a.y - d.y },
      { x: a.x + n.x, y: a.y + n.y },
      { x: b.x + n.x, y: b.y + n.y },
      { x: b.x + d.x, y: b.y + d.y },
      { x: b.x - n.x, y: b.y - n.y },
      { x: a.x - n.x, y: a.y - n.y },
    ];
  } else {
    const c = {
      x: hull.reduce((s, p) => s + p.x, 0) / hull.length,
      y: hull.reduce((s, p) => s + p.y, 0) / hull.length,
    };
    ring = hull.map((p) => {
      const len = Math.hypot(p.x - c.x, p.y - c.y) || 1;
      return {
        x: p.x + ((p.x - c.x) / len) * pad * 1.4,
        y: p.y + ((p.y - c.y) / len) * pad * 1.4,
      };
    });
  }
  const mid = (a: Point, b: Point) => `${(a.x + b.x) / 2},${(a.y + b.y) / 2}`;
  let path = `M${mid(ring[ring.length - 1], ring[0])}`;
  ring.forEach((p, i) => {
    path += `Q${p.x},${p.y} ${mid(p, ring[(i + 1) % ring.length])}`;
  });
  return path + "Z";
}

/** Darker for more recent papers (Connected Papers' year shading), on top of the cluster's colour. */
export function yearShade(
  hex: string,
  year: number | null | undefined,
  min: number,
  max: number,
) {
  const t = year && max > min ? (year - min) / (max - min) : 0.5;
  const mix = 0.55 * (1 - t); // older papers are mixed further towards white
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  const channel = (c: number) =>
    Math.round(c + (255 - c) * mix)
      .toString(16)
      .padStart(2, "0");
  return `#${channel(r)}${channel(g)}${channel(b)}`;
}
