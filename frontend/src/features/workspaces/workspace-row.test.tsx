import { screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { WorkspaceOut } from "@/lib/api/types";
import { renderWithIntl } from "@/test/render";

import { workspaceFixture } from "./test-fixtures";
import { WorkspaceRow } from "./workspace-row";

function renderRow(workspace: WorkspaceOut, locale: "en" | "ru" = "en") {
  return renderWithIntl(
    <ul>
      <WorkspaceRow workspace={workspace} />
    </ul>,
    { locale },
  );
}

describe("WorkspaceRow", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 9, 16, 12, 0));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("links the name to the workspace page", () => {
    const workspace = workspaceFixture(1, { name: "Organic chemistry" });
    renderRow(workspace);

    expect(screen.getByRole("link", { name: "Organic chemistry" })).toHaveAttribute(
      "href",
      `/workspaces/${workspace.id}`,
    );
  });

  it("shows the description, the document counts and the exam countdown", () => {
    renderRow(
      workspaceFixture(1, {
        description: "Midterm: chapters 1 to 6",
        exam_date: "2026-10-28",
        stats: { document_count: 5, ready_count: 3, processing_count: 1, failed_count: 1 },
      }),
    );

    const row = screen.getByRole("listitem");
    expect(within(row).getByText("Midterm: chapters 1 to 6")).toBeInTheDocument();
    expect(within(row).getByText("5 documents")).toBeInTheDocument();
    expect(within(row).getByText("1 processing")).toBeInTheDocument();
    expect(within(row).getByText("1 failed")).toBeInTheDocument();
    expect(within(row).getByText("Exam in 12 days")).toBeInTheDocument();
    expect(within(row).getByText("October 28, 2026")).toBeInTheDocument();
  });

  it("leaves out what a new workspace does not have yet", () => {
    renderRow(workspaceFixture(1));

    const row = screen.getByRole("listitem");
    expect(within(row).getByText("No documents yet")).toBeInTheDocument();
    expect(within(row).queryByText(/processing|failed|Exam/)).not.toBeInTheDocument();
    expect(row.querySelector("time")).toBeNull();
  });

  it("counts only the documents in a state worth noticing", () => {
    renderRow(
      workspaceFixture(1, {
        stats: { document_count: 1, ready_count: 1, processing_count: 0, failed_count: 0 },
      }),
    );

    const row = screen.getByRole("listitem");
    expect(within(row).getByText("1 document")).toBeInTheDocument();
    expect(within(row).queryByText(/processing|failed/)).not.toBeInTheDocument();
  });

  it("renders the name and description as plain text", () => {
    renderRow(
      workspaceFixture(1, {
        name: "<img src=x onerror=alert(1)>",
        description: "<b>not bold</b>",
      }),
    );

    expect(screen.getByRole("link", { name: "<img src=x onerror=alert(1)>" })).toBeInTheDocument();
    expect(screen.getByText("<b>not bold</b>")).toBeInTheDocument();
    expect(document.querySelector("img, b")).toBeNull();
  });

  it.each([
    [1, "1 документ"],
    [3, "3 документа"],
    [5, "5 документов"],
    [21, "21 документ"],
  ])("speaks Russian for %i document(s)", (count, expected) => {
    renderRow(workspaceFixture(1, { stats: { document_count: count, ready_count: count } }), "ru");

    expect(screen.getByText(expected)).toBeInTheDocument();
  });

  it("names documents in progress and failed ones in Russian", () => {
    renderRow(
      workspaceFixture(1, {
        stats: { document_count: 7, processing_count: 2, failed_count: 5 },
      }),
      "ru",
    );

    expect(screen.getByText("2 в обработке")).toBeInTheDocument();
    expect(screen.getByText("5 с ошибкой")).toBeInTheDocument();
    expect(screen.queryByText("Документов пока нет")).not.toBeInTheDocument();
  });
});
