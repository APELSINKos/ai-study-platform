import { documentFixture } from "@/features/documents/test-fixtures";
import type { SearchHit, SearchResults } from "@/lib/api/types";

const RRF_K = 60;
/** Keeps a passage's place in its document apart from its place among the results. */
const FIRST_CHUNK_INDEX = 10;

/**
 * A passage a search found, as the API returns it: the `index`-th result, from 1, in a PDF of
 * lecture notes. The snippet marks the word "light", which the query matched.
 */
export function searchHitFixture(index: number, overrides: Partial<SearchHit> = {}): SearchHit {
  return {
    chunk_id: `00000000-0000-4000-b000-${String(index).padStart(12, "0")}`,
    document_id: documentFixture(1).id,
    document_title: "Lecture 1",
    chunk_index: FIRST_CHUNK_INDEX + index,
    heading: null,
    page_start: index + 1,
    page_end: index + 1,
    snippet: [
      { text: "Chloroplasts turn ", highlighted: false },
      { text: "light", highlighted: true },
      { text: " into the energy of sugar.", highlighted: false },
    ],
    score: 1 / (RRF_K + index),
    matched_by: ["keyword"],
    similarity: null,
    ...overrides,
  };
}

/** The first `count` results of a search over two ready files that compared embeddings too. */
export function searchResultsFixture(
  count: number,
  overrides: Partial<SearchResults> = {},
): SearchResults {
  return {
    results: Array.from({ length: count }, (_, index) => searchHitFixture(index + 1)),
    semantic_available: true,
    searched_document_count: 2,
    stale_document_count: 0,
    pending_document_count: 0,
    ...overrides,
  };
}
