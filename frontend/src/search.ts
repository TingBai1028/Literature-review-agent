import type { Cluster, Paper } from "./types";

function normalize(text: string) {
  return text
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
}

export function searchMap(clusters: Cluster[], papers: Paper[], query: string) {
  const keywords = normalize(query).split(/\s+/).filter(Boolean);
  const matches = (text: string) => {
    const normalized = normalize(text);
    return keywords.every((keyword) => normalized.includes(keyword));
  };
  const titleMatches = new Set(
    papers.filter((paper) => matches(paper.title)).map((paper) => paper.id),
  );
  const paperIds = new Set(titleMatches);
  const clusterIds = new Set<string>();
  for (const cluster of clusters) {
    // A topic match highlights its papers; a title match highlights only that paper.
    if (matches(cluster.label)) {
      clusterIds.add(cluster.id);
      cluster.paper_ids.forEach((id) => paperIds.add(id));
    } else if (cluster.paper_ids.some((id) => titleMatches.has(id))) {
      clusterIds.add(cluster.id);
    }
  }
  return { paperIds, clusterIds, hasQuery: keywords.length > 0 };
}
