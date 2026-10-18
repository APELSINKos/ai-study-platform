import type { ChunkOut, ChunkPage, DocumentOut, DocumentPage } from "@/lib/api/types";

export const WORKSPACE_ID = "00000000-0000-4000-8000-000000000001";

/** A document as the API returns it; `index` keeps ids and file names unique and readable. */
export function documentFixture(index: number, overrides: Partial<DocumentOut> = {}): DocumentOut {
  return {
    id: `00000000-0000-4000-9000-${String(index).padStart(12, "0")}`,
    workspace_id: WORKSPACE_ID,
    original_filename: `lecture-${index}.pdf`,
    content_type: "application/pdf",
    size_bytes: 2_516_582,
    status: "uploaded",
    error_code: null,
    attempts: 0,
    title: null,
    summary: null,
    topics: null,
    difficulty: null,
    estimated_study_minutes: null,
    page_count: null,
    word_count: null,
    chunk_count: null,
    analysis_model: null,
    embedding_model: null,
    processing_ms: null,
    processing_started_at: null,
    processed_at: null,
    created_at: "2026-10-16T09:00:00Z",
    updated_at: "2026-10-16T09:00:00Z",
    can_retry: false,
    ...overrides,
  };
}

/** A processed document with the facts the pipeline fills in. */
export function readyDocumentFixture(
  index: number,
  overrides: Partial<DocumentOut> = {},
): DocumentOut {
  return documentFixture(index, {
    status: "ready",
    attempts: 1,
    title: `Lecture ${index}`,
    page_count: 12,
    word_count: 3412,
    chunk_count: 9,
    analysis_model: "mock-heuristic-v1",
    embedding_model: "mock-hashing-v1",
    processing_ms: 1840,
    processed_at: "2026-10-16T09:00:02Z",
    ...overrides,
  });
}

export function documentPageFixture(
  items: DocumentOut[],
  { page = 1, pageSize = 50, total = items.length } = {},
): DocumentPage {
  return { items, total, page, page_size: pageSize };
}

/** A fragment of a PDF as the API returns it; `index` is its place in the document. */
export function chunkFixture(index: number, overrides: Partial<ChunkOut> = {}): ChunkOut {
  const content = `Passage ${index} of the lecture.`;
  return {
    id: `00000000-0000-4000-a000-${String(index).padStart(12, "0")}`,
    chunk_index: index,
    content,
    heading: null,
    page_start: index + 1,
    page_end: index + 1,
    char_count: content.length,
    ...overrides,
  };
}

export function chunkPageFixture(
  items: ChunkOut[],
  { page = 1, pageSize = 50, total = items.length } = {},
): ChunkPage {
  return { items, total, page, page_size: pageSize };
}
