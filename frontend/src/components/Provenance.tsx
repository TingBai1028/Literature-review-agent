import type { MapResult, Paper, Selection } from "../types";

const relationNames: Record<string, string> = {
  builds_on: "延续 / 扩展",
  same_method_different_domain: "同方法 · 不同领域",
  same_problem_different_method: "同问题 · 不同方法",
  benchmarks_against: "对比 / 基准",
  directly_cites: "直接引用",
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
      <h3>由谁生成、为什么</h3>
      <dl>
        {rows.map(([agent, why]) => (
          <div key={agent}>
            <dt>{agent}</dt>
            <dd>{why}</dd>
          </div>
        ))}
      </dl>
      <button className="text-button small" onClick={onShowReasoning}>
        查看推理过程
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
        "检索代理",
        `来自 ${paper?.source ?? "检索结果"}；按与问题的相关性和引用数排序后入选地图。`,
      ],
      [
        "聚类代理",
        `归入「${cluster?.label ?? "未分组"}」${detail ? `；与问题相似度 ${detail.question_similarity.toFixed(2)}；${detail.reason}` : "。"}`,
      ],
    ];
  }
  if (s.type === "cluster") {
    const c = map.clusters.find((x) => x.id === s.id);
    return c
      ? [
          ["聚类代理", c.role_reason ?? "按内容相似度分组。"],
          ["命名", c.rationale || "名称尚未生成。"],
        ]
      : [];
  }
  if (s.type === "connection") {
    const c = map.connections.find((x) => x.id === s.id);
    return c
      ? [
          [
            "关联代理",
            `${relationNames[c.relation ?? ""] ?? "关联"}：${c.reason_short ?? c.description}`,
          ],
          [
            "独立审核",
            map.sample_mode
              ? "样例占位结果，未经模型审核。"
              : c.evidence.length
                ? "独立审核代理对照两篇原文核验通过；泛泛的理由会被退回重写一次。"
                : "实时结果：保存后显示原文证据。",
          ],
        ]
      : [];
  }
  const g = map.gaps.find((x) => x.id === s.id);
  return g
    ? [
        [
          "研究空白代理",
          `${g.gap_type === "explicit" ? "作者在摘要中明确陈述" : "由两篇论文推断"}；${g.description}`,
        ],
        [
          "评分代理",
          g.label
            ? `标为 ${g.label}${g.label_reason ? `：${g.label_reason}` : ""}`
            : "尚未评级。",
        ],
        [
          "覆盖检索",
          (
            {
              not_filled: "检索结果中未发现已有研究填补此空白。",
              unavailable: "检索不可用，未作为空白证据。",
              skipped: "未执行检索。",
            } as Record<string, string>
          )[g.coverage_status ?? ""] ?? "尚未检索。",
        ],
      ]
    : [];
}
