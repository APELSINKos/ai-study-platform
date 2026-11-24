import type { CitationOut } from "@/lib/api/types";

export type AnswerPart =
  { kind: "text"; text: string } | { kind: "citation"; citation: CitationOut };

const PARAGRAPH_BREAK = /\n{2,}/;
const CITATION_MARKER = /\[(\d{1,3})\]/g;

/**
 * Splits a grounded answer into paragraphs and linear-time inline text/citation tokens.
 * Bracketed numbers without a matching citation (such as years like `[2024]`) remain plain text.
 */
export function tokenizeAnswerParagraphs(
  content: string,
  citations: readonly CitationOut[],
): AnswerPart[][] {
  const byIndex = new Map<number, CitationOut>();
  for (const citation of citations) {
    byIndex.set(citation.index, citation);
  }

  const paragraphs = content
    .split(PARAGRAPH_BREAK)
    .map((paragraph) => paragraph.trim())
    .filter((paragraph) => paragraph.length > 0);

  return paragraphs.map((paragraph) => tokenizeParagraph(paragraph, byIndex));
}

function tokenizeParagraph(
  paragraph: string,
  byIndex: ReadonlyMap<number, CitationOut>,
): AnswerPart[] {
  const parts: AnswerPart[] = [];
  let cursor = 0;

  for (const match of paragraph.matchAll(CITATION_MARKER)) {
    const matchIndex = match.index;
    if (matchIndex === undefined) {
      continue;
    }
    const citation = byIndex.get(Number(match[1]));
    if (citation === undefined) {
      continue;
    }
    if (matchIndex > cursor) {
      parts.push({ kind: "text", text: paragraph.slice(cursor, matchIndex) });
    }
    parts.push({ kind: "citation", citation });
    cursor = matchIndex + match[0].length;
  }

  if (cursor < paragraph.length) {
    parts.push({ kind: "text", text: paragraph.slice(cursor) });
  }

  return parts.length > 0 ? parts : [{ kind: "text", text: paragraph }];
}
