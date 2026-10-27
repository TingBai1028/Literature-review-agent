import type { MapResult, Paper, Selection } from "../types";
import { ExplanationText } from "./ExplanationText";

const relationNames: Record<string, string> = {
  builds_on: "Builds on",
  same_method_different_domain: "Same method · different domain",
  same_problem_different_method: "Same problem · different method",
  benchmarks_against: "Benchmarks against",
  directly_cites: "Directly cites",
};
type Context = [label: string, value: string][];
type ProvenanceRow = {
  agent: string;
  why: string;
  context?: Context;
  status?: string;
};
const row = (agent: string, why: string, context?: Context): ProvenanceRow => ({
  agent,
  why,
  context,
});

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
  onShowReasoning?: () => void;
}) {
  const rows = provenance(map, papers, selection);
  if (!rows.length) return null;
  return (
    <section className="inspector-section provenance">
      <h3>Who made this, and why</h3>
      <dl>
        {rows.map(({ agent, why, context, status }) => (
          <div className="provenance-entry" key={agent}>
            <dt>
              {agent}
              {status && <span className="provenance-status">{status}</span>}
            </dt>
            <dd>
              {context && (
                <div className="provenance-context">
                  {context.map(([label, value]) => (
                    <p key={label}>
                      <span>{label}</span>
                      <strong>{value}</strong>
                    </p>
                  ))}
                </div>
              )}
              <ExplanationText text={why} papers={papers} />
            </dd>
          </div>
        ))}
      </dl>
      <button
        className="text-button small"
        onClick={onShowReasoning}
        disabled={!onShowReasoning}
      >
        Show reasoning
      </button>
    </section>
  );
}

function provenance(
  map: MapResult,
  papers: Paper[],
  s: Selection | null,
): ProvenanceRow[] {
  if (!s) return [];
  if (s.type === "paper") {
    const paper = papers.find((p) => p.id === s.id);
    const cluster = map.clusters.find((c) => c.paper_ids.includes(s.id));
    const detail = cluster?.paper_details?.find((d) => d.paper_id === s.id);
    const source =
      (
        {
          openalex: "OpenAlex",
          arxiv: "arXiv",
          semantic_scholar: "Semantic Scholar",
        } as Record<string, string>
      )[paper?.source ?? ""] ??
      paper?.source ??
      "search results";
    return [
      row(
        "Retriever",
        `Retrieved from ${source}. Selected for the map by relevance to your question and citations.`,
      ),
      row(
        "Clusterer",
        detail?.reason ||
          "Assigned by the question relevance and cluster membership rules.",
        [
          ["Assigned topic", cluster?.label ?? "Ungrouped"],
          ...(detail
            ? [
                [
                  "Question similarity",
                  detail.question_similarity.toFixed(2),
                ] as [string, string],
              ]
            : []),
        ],
      ),
    ];
  }
  if (s.type === "cluster") {
    const c = map.clusters.find((x) => x.id === s.id);
    if (!c) return [];
    const assessment = c.rationale.match(
      /^\[(coherent|mixed|uncertain|singleton)\]\s*/i,
    );
    return [
      row("Clusterer", c.role_reason ?? "Grouped by content similarity."),
      {
        ...row(
          "Naming",
          assessment
            ? c.rationale.slice(assessment[0].length)
            : c.rationale || "No name yet.",
        ),
        status: assessment?.[1],
      },
    ];
  }
  if (s.type === "connection") {
    const c = map.connections.find((x) => x.id === s.id);
    return c
      ? [
          row("Connection finder", c.reason_short ?? c.description, [
            ["Relationship", relationNames[c.relation ?? ""] ?? "Connection"],
          ]),
          row(
            "Independent check",
            map.sample_mode
              ? "Sample placeholder; not checked by a model."
              : c.evidence.length
                ? "An independent checker verified it against both papers; generic reasons are sent back for one rewrite."
                : "Live result: source evidence appears once saved.",
          ),
        ]
      : [];
  }
  const g = map.gaps.find((x) => x.id === s.id);
  return g
    ? [
        row("Gap finder", g.description, [
          [
            "Basis",
            g.gap_type === "explicit"
              ? "Stated by the authors in the abstract"
              : "Inferred from two papers",
          ],
        ]),
        row(
          "Grader",
          g.label
            ? [
                g.label_reason,
                g.label === "novel" &&
                !map.sample_mode &&
                g.coverage_status !== "not_filled"
                  ? "Novelty unverified: no completed coverage search, so it is listed after verified gaps."
                  : "",
              ]
                .filter(Boolean)
                .join("\n\n") || "No grading explanation was recorded."
            : "Not graded yet.",
          g.label ? [["Assessment", g.label.replaceAll("_", " ")]] : undefined,
        ),
        row(
          "Coverage search",
          (
            {
              not_filled:
                "No prior work addressing this gap was found in the checked sources.",
              unavailable:
                "Search unavailable; not counted as evidence of a gap.",
              skipped: "No search was run.",
            } as Record<string, string>
          )[g.coverage_status ?? ""] ?? "Not searched yet.",
        ),
      ]
    : [];
}
