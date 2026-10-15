import type { WorkspaceOut, WorkspacePage, WorkspaceStats } from "@/lib/api/types";

const NO_DOCUMENTS: WorkspaceStats = {
  document_count: 0,
  ready_count: 0,
  processing_count: 0,
  failed_count: 0,
  estimated_study_minutes: 0,
};

/** A workspace as the API returns it; `index` keeps ids and names unique and readable. */
export function workspaceFixture(
  index: number,
  overrides: Partial<Omit<WorkspaceOut, "stats">> & { stats?: Partial<WorkspaceStats> } = {},
): WorkspaceOut {
  const { stats, ...fields } = overrides;
  return {
    id: `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`,
    name: `Workspace ${index}`,
    description: null,
    exam_date: null,
    created_at: "2026-10-01T09:00:00Z",
    updated_at: "2026-10-01T09:00:00Z",
    ...fields,
    stats: { ...NO_DOCUMENTS, ...stats },
  };
}

export function workspacePageFixture(
  items: WorkspaceOut[],
  { page = 1, pageSize = 20, total = items.length } = {},
): WorkspacePage {
  return { items, total, page, page_size: pageSize };
}
