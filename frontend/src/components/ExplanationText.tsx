import type { ReactNode } from "react";
import { PaperText } from "../paperNames";
import type { Paper } from "../types";

// Render the small amount of formatting agents commonly use, without interpreting HTML or URLs.
function inline(text: string, papers: Paper[]): ReactNode[] {
  const pattern = /\*\*([^*\n]+)\*\*|__([^_\n]+)__|`([^`\n]+)`|\*([^*\n]+)\*/g;
  const nodes: ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    nodes.push(
      <PaperText
        key={`text-${last}`}
        text={text.slice(last, match.index)}
        papers={papers}
      />,
    );
    const content = (
      <PaperText
        text={match[1] ?? match[2] ?? match[3] ?? match[4]}
        papers={papers}
      />
    );
    nodes.push(
      match[3] !== undefined ? (
        <code key={match.index}>{content}</code>
      ) : match[4] !== undefined ? (
        <em key={match.index}>{content}</em>
      ) : (
        <strong key={match.index}>{content}</strong>
      ),
    );
    last = match.index! + match[0].length;
  }
  nodes.push(
    <PaperText key={`text-${last}`} text={text.slice(last)} papers={papers} />,
  );
  return nodes;
}

function paragraphs(text: string): string[] {
  // Keep author-supplied formatting intact; add spacing only to long plain prose.
  if (
    text.length < 650 ||
    text.includes("\n") ||
    /[*`]/.test(text) ||
    text.includes("__")
  )
    return [text];
  const sentences = new Intl.Segmenter("en", {
    granularity: "sentence",
  }).segment(text);
  const parts: string[] = [];
  let part = "";
  for (const { segment } of sentences) {
    if (part.length >= 350) {
      parts.push(part.trim());
      part = "";
    }
    part += segment;
  }
  if (part) parts.push(part.trim());
  return parts;
}

export function ExplanationText({
  text,
  papers,
}: {
  text: string;
  papers: Paper[];
}) {
  const lines = (text.trim() || "No explanation was recorded.")
    .replace(/\r\n?/g, "\n")
    .split("\n");
  const blocks: ReactNode[] = [];
  const listItem = (line: string) =>
    line.match(/^\s*(?:([-*•])\s+|(\d+)[.)]\s+)(.*)$/);
  const heading = (line: string) => line.match(/^\s*#{1,6}\s+(.+)$/);
  for (let i = 0; i < lines.length;) {
    if (!lines[i].trim()) {
      i++;
      continue;
    }
    const title = heading(lines[i]);
    if (title) {
      blocks.push(<h4 key={i}>{inline(title[1], papers)}</h4>);
      i++;
      continue;
    }
    const item = listItem(lines[i]);
    if (item) {
      const start = i,
        ordered = !!item[2],
        children: ReactNode[] = [];
      while (i < lines.length) {
        const next = listItem(lines[i]);
        if (!next || !!next[2] !== ordered) break;
        children.push(<li key={i}>{inline(next[3], papers)}</li>);
        i++;
      }
      blocks.push(
        ordered ? (
          <ol start={Number(item[2])} key={start}>
            {children}
          </ol>
        ) : (
          <ul key={start}>{children}</ul>
        ),
      );
      continue;
    }
    const start = i,
      paragraph: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !listItem(lines[i]) &&
      !heading(lines[i])
    )
      paragraph.push(lines[i++]);
    paragraphs(paragraph.join("\n")).forEach((part, index) =>
      blocks.push(<p key={`${start}-${index}`}>{inline(part, papers)}</p>),
    );
  }
  return <div className="explanation-text">{blocks}</div>;
}
