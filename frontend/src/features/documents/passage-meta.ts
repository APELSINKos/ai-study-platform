/** How the API joins the headings above a passage. */
export const HEADING_SEPARATOR = " › ";

export interface PassageHeadingSource {
  document_title: string;
  heading: string | null;
}

export interface PassagePageSource {
  page_start: number | null;
  page_end: number | null;
}

export interface PageRangeFormat {
  page: (page: number) => string;
  pages: (start: number, end: number) => string;
}

/**
 * The headings above a passage, without the document's title when they start with it: a Markdown
 * file is named after its first heading. Null when no other heading is left.
 */
export function headingBelowTitle(passage: PassageHeadingSource): string | null {
  if (passage.heading === null || passage.heading === passage.document_title) {
    return null;
  }
  const title = passage.document_title + HEADING_SEPARATOR;
  return passage.heading.startsWith(title) ? passage.heading.slice(title.length) : passage.heading;
}

/** A translated page label ("Page 4" or "Pages 4–5"), or null for files without pages. */
export function pageRange(passage: PassagePageSource, format: PageRangeFormat): string | null {
  if (passage.page_start === null) {
    return null;
  }
  const end = passage.page_end ?? passage.page_start;
  return end === passage.page_start
    ? format.page(passage.page_start)
    : format.pages(passage.page_start, end);
}
