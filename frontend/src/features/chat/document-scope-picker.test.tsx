import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { documentPageFixture, readyDocumentFixture } from "@/features/documents/test-fixtures";
import { apiFetch } from "@/lib/api/client";
import { renderWithIntl } from "@/test/render";

import {
  DocumentScopePicker,
  reconcileScopeDocumentIds,
  type ScopeMode,
} from "./document-scope-picker";
import { CHAT_WORKSPACE_ID } from "./test-fixtures";

vi.mock("@/lib/api/client", () => ({ apiFetch: vi.fn() }));
const apiFetchMock = vi.mocked(apiFetch);

const DOC_1 = readyDocumentFixture(1, { workspace_id: CHAT_WORKSPACE_ID, title: "Chapter 1" });
const DOC_2 = readyDocumentFixture(2, { workspace_id: CHAT_WORKSPACE_ID, title: "Chapter 2" });
const DOC_3 = readyDocumentFixture(3, { workspace_id: CHAT_WORKSPACE_ID, title: "Chapter 3" });

describe("reconcileScopeDocumentIds", () => {
  it("intersects selected IDs with existing documents and converts empty to null", () => {
    expect(reconcileScopeDocumentIds([DOC_1.id, "stale-id"], [DOC_1, DOC_2], false)).toEqual([
      DOC_1.id,
    ]);
    expect(reconcileScopeDocumentIds(["stale-only"], [DOC_1, DOC_2], false)).toBeNull();
    expect(reconcileScopeDocumentIds([], [DOC_1, DOC_2], false)).toBeNull();
  });

  it("preserves IDs from unloaded pages while hasUnloadedPages is true", () => {
    expect(reconcileScopeDocumentIds([DOC_1.id, DOC_3.id], [DOC_1, DOC_2], true)).toEqual([
      DOC_1.id,
      DOC_3.id,
    ]);
    expect(reconcileScopeDocumentIds([], [DOC_1, DOC_2], true)).toBeNull();
  });
});

describe("DocumentScopePicker", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it("loads additional document pages via Show more documents", async () => {
    apiFetchMock.mockImplementation(async (path) => {
      if (path.includes("page=1")) {
        return documentPageFixture([DOC_1, DOC_2], { page: 1, pageSize: 2, total: 3 });
      }
      return documentPageFixture([DOC_3], { page: 2, pageSize: 2, total: 3 });
    });

    const onScopeModeChange = vi.fn<(mode: ScopeMode) => void>();
    const onSelectedIdsChange = vi.fn<(ids: string[]) => void>();

    renderWithIntl(
      <DocumentScopePicker
        workspaceId={CHAT_WORKSPACE_ID}
        scopeMode="selected"
        onScopeModeChange={onScopeModeChange}
        selectedIds={[]}
        onSelectedIdsChange={onSelectedIdsChange}
        maxScopeDocuments={50}
      />,
    );

    expect(await screen.findByRole("checkbox", { name: "Chapter 1" })).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Chapter 3" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Show more documents" }));

    expect(await screen.findByRole("checkbox", { name: "Chapter 3" })).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Show more documents" })).not.toBeInTheDocument(),
    );
  });
});
