import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type * as MotionModule from "motion/react";
import { createRef } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Locale } from "@/i18n/config";
import { apiFetch } from "@/lib/api/client";
import type { DocumentOut } from "@/lib/api/types";
import { renderWithIntl } from "@/test/render";

import { DocumentRow } from "./document-row";
import { documentFixture, readyDocumentFixture } from "./test-fixtures";

vi.mock("@/lib/api/client", () => ({ apiFetch: vi.fn() }));

const motionPreference = vi.hoisted(() => ({ reduce: false }));

vi.mock("motion/react", async (importOriginal) => ({
  ...(await importOriginal<typeof MotionModule>()),
  useReducedMotion: () => motionPreference.reduce,
}));

const apiFetchMock = vi.mocked(apiFetch);

function renderRow(document: DocumentOut, locale: Locale = "en"): HTMLElement {
  renderWithIntl(
    <ul>
      <DocumentRow document={document} focusAfterDelete={createRef<HTMLElement>()} />
    </ul>,
    { locale },
  );
  return screen.getByRole("listitem");
}

function railOf(row: HTMLElement): SVGSVGElement | null {
  return row.querySelector("svg[aria-hidden='true'] [data-stage]")?.closest("svg") ?? null;
}

function currentStage(row: HTMLElement): string | null {
  return railOf(row)?.querySelector("[data-state='current']")?.getAttribute("data-stage") ?? null;
}

describe("DocumentRow", () => {
  beforeEach(() => {
    motionPreference.reduce = false;
    apiFetchMock.mockReset();
  });

  it("links the document's title to its page and shows the whole title on hover", () => {
    const row = renderRow(readyDocumentFixture(1, { title: "Reaction mechanisms" }));

    const link = within(row).getByRole("link", { name: "Reaction mechanisms" });
    expect(link).toHaveAttribute("href", `/documents/${readyDocumentFixture(1).id}`);
    expect(link).toHaveAttribute("title", "Reaction mechanisms");
    expect(link).toHaveClass("truncate");
  });

  it("names a document by its file until it has a title", () => {
    const row = renderRow(documentFixture(1, { original_filename: "week-3 notes.md" }));

    expect(within(row).getByRole("link", { name: "week-3 notes.md" })).toHaveAttribute(
      "title",
      "week-3 notes.md",
    );
  });

  it("states the size, the pages and the words as separate facts", () => {
    const row = renderRow(readyDocumentFixture(1, { page_count: 12, word_count: 3412 }));

    expect(within(row).getByText("2.4 MB").tagName).toBe("SPAN");
    expect(within(row).getByText("12 pages").tagName).toBe("SPAN");
    expect(within(row).getByText("3,412 words").tagName).toBe("SPAN");
  });

  it("leaves out the pages and the words until they are known", () => {
    const row = renderRow(
      documentFixture(1, { content_type: "text/plain", size_bytes: 900, page_count: null }),
    );

    expect(within(row).getByText("900 bytes")).toBeInTheDocument();
    expect(within(row).queryByText(/page/)).not.toBeInTheDocument();
    expect(within(row).queryByText(/word/)).not.toBeInTheDocument();
  });

  it("counts a single page and word in the singular", () => {
    const row = renderRow(readyDocumentFixture(1, { page_count: 1, word_count: 1 }));

    expect(within(row).getByText("1 page")).toBeInTheDocument();
    expect(within(row).getByText("1 word")).toBeInTheDocument();
  });

  it("marks each file type with an icon of its own", () => {
    const icons = (["application/pdf", "text/markdown", "text/plain"] as const).map(
      (contentType, index) => {
        const { unmount } = renderWithIntl(
          <ul>
            <DocumentRow
              document={readyDocumentFixture(index, { content_type: contentType })}
              focusAfterDelete={createRef<HTMLElement>()}
            />
          </ul>,
        );
        const icon = screen.getByRole("listitem").querySelector("svg");
        const markup = icon?.innerHTML ?? "";
        expect(icon).toHaveAttribute("aria-hidden", "true");
        unmount();
        return markup;
      },
    );

    expect(new Set(icons).size).toBe(3);
  });

  it("says a ready document is ready, with no rail", () => {
    const row = renderRow(readyDocumentFixture(1));

    expect(within(row).getByText("Ready")).toBeInTheDocument();
    expect(railOf(row)).toBeNull();
  });

  it.each([
    ["uploaded", "In the queue"],
    ["processing", "Reading and analysing"],
    ["indexing", "Preparing for search"],
  ] as const)("tells the stage of a %s document beside its rail", (status, label) => {
    const row = renderRow(documentFixture(1, { status }));

    expect(within(row).getByText(label)).toBeInTheDocument();
    expect(currentStage(row)).toBe(status);
    expect(railOf(row)?.querySelector("[data-running]")).toHaveAttribute(
      "data-running",
      "animated",
    );
  });

  it("keeps the rail still when the user asks for less motion", () => {
    motionPreference.reduce = true;

    const row = renderRow(documentFixture(1, { status: "processing" }));

    expect(railOf(row)?.querySelector("[data-running]")).toHaveAttribute("data-running", "still");
  });

  it("says a retry is coming after the AI service did not answer", () => {
    const row = renderRow(documentFixture(1, { status: "uploaded", error_code: "ai_unavailable" }));

    expect(within(row).getByText("Retrying soon")).toBeInTheDocument();
    expect(within(row).queryByText("In the queue")).not.toBeInTheDocument();
    expect(currentStage(row)).toBe("uploaded");
    expect(railOf(row)?.querySelector("[data-running]")).toBeNull();
  });

  it("notes that a stalled document is taking longer than usual", () => {
    const row = renderRow(documentFixture(1, { status: "processing", can_retry: true }));

    expect(within(row).getByText("Reading and analysing")).toBeInTheDocument();
    expect(within(row).getByText("This is taking longer than usual.")).toBeInTheDocument();
    expect(railOf(row)?.querySelector("[data-running]")).toBeNull();
  });

  it("says why a document failed", () => {
    const row = renderRow(
      documentFixture(1, { status: "failed", error_code: "pdf_unreadable", can_retry: true }),
    );

    expect(within(row).getByText("Failed")).toBeInTheDocument();
    expect(
      within(row).getByText("The PDF could not be read. The file may be damaged."),
    ).toHaveClass("text-margin");
    expect(railOf(row)?.querySelector("[data-failure]")).not.toBeNull();
  });

  it("keeps the stage words out of the status colours", () => {
    const row = renderRow(documentFixture(1, { status: "processing" }));

    expect(within(row).getByText("Reading and analysing").closest("p")).not.toHaveClass("text-pen");
    expect(within(row).getByText("Reading and analysing").closest("p")).toHaveClass("text-ink");
  });

  it("renders a title as plain text", () => {
    const row = renderRow(readyDocumentFixture(1, { title: "<img src=x onerror=alert(1)>" }));

    expect(within(row).getByRole("link", { name: "<img src=x onerror=alert(1)>" })).toBeVisible();
    expect(row.querySelector("img")).toBeNull();
  });

  it("speaks Russian", () => {
    const row = renderRow(
      readyDocumentFixture(1, { status: "processing", page_count: 12, word_count: 3412 }),
      "ru",
    );

    expect(within(row).getByText("Чтение и анализ")).toBeInTheDocument();
    expect(within(row).getByText("2,4 МБ")).toBeInTheDocument();
    expect(within(row).getByText("12 страниц")).toBeInTheDocument();
    // The matcher folds the no-break space that groups the digits into a plain one.
    expect(within(row).getByText("3 412 слов")).toBeInTheDocument();
  });

  it("says why a document failed in Russian", () => {
    const row = renderRow(
      documentFixture(1, { status: "failed", error_code: "no_text", can_retry: true }),
      "ru",
    );

    expect(within(row).getByText("Не обработан")).toBeInTheDocument();
    expect(
      within(row).getByText(
        "В файле не найден текст. У отсканированного PDF должен быть текстовый слой.",
      ),
    ).toBeInTheDocument();
  });

  it("offers Retry beside the reason a document failed", () => {
    const row = renderRow(
      documentFixture(1, { status: "failed", error_code: "pdf_unreadable", can_retry: true }),
    );

    const retry = within(row).getByRole("button", { name: "Retry lecture-1.pdf" });
    expect(retry).toHaveTextContent("Retry");
    expect(retry).toHaveAttribute("data-variant", "secondary");
  });

  it("offers Retry beside the note that a document has stalled", () => {
    const row = renderRow(documentFixture(1, { status: "indexing", can_retry: true }));

    expect(within(row).getByText("This is taking longer than usual.")).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "Retry lecture-1.pdf" })).toBeInTheDocument();
  });

  it.each([
    ["moves on", documentFixture(1, { status: "processing" })],
    ["waits for its automatic retry", documentFixture(1, { error_code: "ai_unavailable" })],
    ["is ready", readyDocumentFixture(1)],
  ])("offers no Retry while a document %s", (_, document) => {
    const row = renderRow(document);

    expect(within(row).queryByRole("button", { name: /Retry/ })).not.toBeInTheDocument();
  });

  it.each([
    readyDocumentFixture(1, { original_filename: "lecture-1.pdf" }),
    documentFixture(1, { status: "processing" }),
    documentFixture(1, { status: "failed", error_code: "no_text", can_retry: true }),
  ])("offers deleting as a quiet icon button named after the file", (document) => {
    const row = renderRow(document);

    const remove = within(row).getByRole("button", { name: "Delete lecture-1.pdf" });
    expect(remove).toHaveAttribute("data-variant", "ghost");
    expect(remove).toHaveTextContent("");
    expect(row.querySelector('[data-variant="primary"]')).toBeNull();
  });

  it("asks before deleting and names the file", async () => {
    const row = renderRow(readyDocumentFixture(1, { title: "Reaction mechanisms" }));

    await userEvent.click(within(row).getByRole("button", { name: "Delete lecture-1.pdf" }));

    const dialog = await screen.findByRole("alertdialog", { name: "Delete this document?" });
    expect(dialog).toHaveAccessibleDescription(
      "“lecture-1.pdf” will be deleted. This cannot be undone.",
    );
    expect(within(dialog).getByRole("button", { name: "Delete document" })).toHaveAttribute(
      "data-variant",
      "danger",
    );
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("offers Retry and deleting in Russian", async () => {
    const row = renderRow(
      documentFixture(1, { status: "failed", error_code: "no_text", can_retry: true }),
      "ru",
    );

    expect(
      within(row).getByRole("button", { name: "Повторить обработку lecture-1.pdf" }),
    ).toHaveTextContent("Повторить");
    await userEvent.click(within(row).getByRole("button", { name: "Удалить lecture-1.pdf" }));

    const dialog = await screen.findByRole("alertdialog", { name: "Удалить этот документ?" });
    expect(dialog).toHaveAccessibleDescription(
      "Файл «lecture-1.pdf» будет удалён. Это нельзя отменить.",
    );
    expect(within(dialog).getByRole("button", { name: "Удалить документ" })).toBeInTheDocument();
  });
});
