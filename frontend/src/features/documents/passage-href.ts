/** The page of a document, opened at one of its passages: the one at `chunkIndex`, from 0. */
export function passageHref(documentId: string, chunkIndex: number): string {
  return `/documents/${encodeURIComponent(documentId)}?fragment=${chunkIndex}`;
}
