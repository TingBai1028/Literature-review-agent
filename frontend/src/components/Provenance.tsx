import type { MapResult, Paper, Selection } from "../types";
import { PaperText } from "../paperNames";

const relationNames: Record<string, string> = {
  builds_on: "Builds on",
  same_method_different_domain: "Same method · different domain",
  same_problem_different_method: "Same problem · different method",
  benchmarks_against: "Benchmarks against",
  directly_cites: "Directly cites",
};

/** Spec B6: which agent created the selected map element, and why. */
export function Provenance({
  map,
  papers,
  selection,
  onShowReasoning,
}: {
  map: MapResult;
  papers: Paper[];
  selection: Selection | null;
  onShowReasoning: () => void;
}) {
  const rows = provenance(map, papers, selection);
  if (!rows.length) return null;
  return (
    <section className="inspector-section provenance">
      <h3>Who made this, and why</h3>
      <dl>
        {rows.map(([agent, why]) => (
          <div key={agent}>
            <dt>{agent}</dt>
            <dd>
              <PaperText text={why} papers={papers} />
            </dd>
          </div>
        ))}
      </dl>
      <button className="text-button small" onClick={onShowReasoning}>
        Show reasoning
      </button>
    </section>
  );
}

function provenance(
  map: MapResult,
  papers: Paper[],
  s: Selection | null,
): [string, string][] {
  if (!s) return [];
  if (s.type === "paper") {
    const paper = papers.find((p) => p.id === s.id);
    const cluster = map.clusters.find((c) => c.paper_ids.includes(s.id));
    const detail = cluster?.paper_details?.find((d) => d.paper_id === s.id);
    return [
      [
        "Retriever",
        `From ${paper?.source ?? "search results"}; chosen for the map after ranking by relevance to the question and citations.`,
      ],
      [
        "Clusterer",
        `Placed in "${cluster?.label ?? "Ungrouped"}"${detail ? `; similarity to the question ${detail.question_similarity.toFixed(2)}; ${detail.reason}` : "."}`,
      ],
    ];
  }
  if (s.type === "cluster") {
    const c = map.clusters.find((x) => x.id === s.id);
    return c
      ? [
          ["Clusterer", c.role_reason ?? "Grouped by content similarity."],
          ["Naming", c.rationale || "No name yet."],
        ]
      : [];
  }
  if (s.type === "connection") {
    const c = map.connections.find((x) => x.id === s.id);
    return c
      ? [
          [
            "Connection finder",
            `${relationNames[c.relation ?? ""] ?? "Connection"}: ${c.reason_short ?? c.description}`,
          ],
          [
            "Independent check",
            map.sample_mode
              ? "Sample placeholder; not checked by a model."
              : c.evidence.length
                ? "An independent checker verified it against both papers; generic reasons are sent back for one rewrite."
                : "Live result: source evidence appears once saved.",
          ],
        ]
      : [];
  }
  const g = map.gaps.find((x) => x.id === s.id);
  return g
    ? [
        [
          "Gap finder",
          `${g.gap_type === "explicit" ? "Stated by the authors in the abstract" : "Inferred from two papers"}; ${g.description}`,
        ],
        [
          "Grader",
          g.label
            ? `Labelled ${g.label}${g.label === "novel" && !map.sample_mode && g.coverage_status !== "not_filled" ? " (novelty unverified: no completed coverage search, so it is listed after verified gaps)" : ""}${g.label_reason ? `: ${g.label_reason}` : ""}`
            : "Not graded yet.",
        ],
        [
          "Coverage search",
          (
            {
              not_filled: "The search found no prior work that fills this gap.",
              unavailable: "Search unavailable; not counted as evidence of a gap.",
              skipped: "No search was run.",
            } as Record<string, string>
          )[g.coverage_status ?? ""] ?? "Not searched yet.",
        ],
      ]
    : [];
}
