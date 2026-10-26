import type { ReactNode } from "react";
import type { Paper, Selection } from "./types";

// Agents name papers by ID in what they write ("W2951392766 shows that…", "(arXiv:1805.07220)"), because their
// evidence is checked by ID. Readers see the paper's short title instead; hovering shows the full reference.

type Named = Pick<Paper, "id" | "title"> & Partial<Pick<Paper, "year" | "authors">>;

/** A paper's title cut to its first eight words. */
export function shortTitle(p: Named) {
  const words = p.title.trim().split(/\s+/);
  return words.length > 8 ? words.slice(0, 8).join(" ") + "…" : p.title.trim();
}

function reference(p: Named) {
  const author = p.authors?.[0];
  const who = author ? `${author}${(p.authors?.length ?? 0) > 1 ? " et al." : ""}` : "";
  const meta = [who, p.year].filter(Boolean).join(", ");
  return meta ? `${p.title} (${meta})` : p.title;
}

/** Only the IDs of papers in this map, longest first; IDs under 4 characters (sample "P0") are left alone. */
function idPattern(papers: Named[]) {
  const ids = papers
    .map((p) => p.id)
    .filter((id) => id.length >= 4)
    .sort((a, b) => b.length - a.length)
    .map((id) => id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  return ids.length ? new RegExp(`(?<![\\w:.])(${ids.join("|")})(?!\\w)`, "g") : null;
}

/** Plain text with paper IDs replaced by quoted short titles, for tooltips and accessible names. */
export function namePapers(text: string, papers: Named[]) {
  const pattern = idPattern(papers);
  if (!pattern || !text) return text;
  const byId = new Map(papers.map((p) => [p.id, p]));
  return text.replace(pattern, (id) => `“${shortTitle(byId.get(id)!)}”`);
}

/** Text with each paper ID shown as the paper's short title; clicking it opens the paper when onSelect is given. */
export function PaperText({
  text,
  papers,
  onSelect,
}: {
  text: string | null | undefined;
  papers: Named[];
  onSelect?: (s: Selection) => void;
}) {
  const pattern = text ? idPattern(papers) : null;
  if (!text || !pattern) return <>{text}</>;
  const byId = new Map(papers.map((p) => [p.id, p]));
  const out: ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    const p = byId.get(match[0])!;
    out.push(text.slice(last, match.index));
    out.push(
      onSelect ? (
        // A link, not a button: a button is laid out as one box, so a long name broke out of the sentence.
        <a
          key={match.index}
          href={`#paper-${p.id}`}
          className="paper-ref"
          title={reference(p)}
          onClick={(e) => {
            e.preventDefault();
            onSelect({ type: "paper", id: p.id });
          }}
        >
          “{shortTitle(p)}”
        </a>
      ) : (
        <span key={match.index} className="paper-ref" title={reference(p)}>
          “{shortTitle(p)}”
        </span>
      ),
    );
    last = match.index! + match[0].length;
  }
  out.push(text.slice(last));
  return <>{out}</>;
}
