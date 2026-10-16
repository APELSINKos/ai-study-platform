import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Locale } from "@/i18n/config";
import { ApiError } from "@/lib/api/errors";
import { renderWithIntl } from "@/test/render";

import type { FileRules } from "./file-rules";
import { UploadResults } from "./upload-results";
import type { UploadItem, UploadState } from "./use-upload-queue";

const MIB = 1024 * 1024;
const RULES: FileRules = {
  allowed_extensions: [".pdf", ".md", ".txt"],
  max_upload_bytes: 20 * MIB,
};

const waiting: UploadState = { kind: "waiting" };
const uploading: UploadState = { kind: "uploading" };
const uploaded: UploadState = { kind: "uploaded" };

function refusedWith(code: string, status = 409): UploadState {
  return {
    kind: "failed",
    error: new ApiError({ status, code, message: "The backend's own English." }),
  };
}

let lastId = 0;

function item(name: string, state: UploadState, size = 3 * 1024): UploadItem {
  lastId += 1;
  return { id: lastId, name, size, state };
}

function renderResults(items: UploadItem[], locale: Locale = "en", onClear = vi.fn()) {
  return renderWithIntl(<UploadResults items={items} onClear={onClear} />, { locale });
}

/** What the row of a file says became of it. */
function outcomeOf(name: string): string {
  const outcome = screen.getByTitle(name).closest("li")?.querySelector("[data-outcome]");
  if (!outcome) {
    throw new Error(`No outcome for ${name}.`);
  }
  return outcome.textContent ?? "";
}

describe("UploadResults", () => {
  it("keeps its live region in place before any file is added", () => {
    renderResults([]);

    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("lists each file with its size and where it stands", () => {
    renderResults([
      item("notes.md", uploaded, 3 * 1024),
      item("lecture.pdf", uploading, 2_516_582),
      item("syllabus.txt", waiting, 512),
    ]);

    const list = screen.getByRole("list", { name: "Upload results" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(3);
    expect(outcomeOf("notes.md")).toBe("Uploaded");
    expect(outcomeOf("lecture.pdf")).toBe("Uploading…");
    expect(outcomeOf("syllabus.txt")).toBe("Waiting");
    expect(within(list).getByText("3 kB")).toBeInTheDocument();
    expect(within(list).getByText("2.4 MB")).toBeInTheDocument();
    expect(within(list).getByText("512 bytes")).toBeInTheDocument();
  });

  it("says why a file was turned down before it was sent", () => {
    renderResults([
      item("timetable.docx", { kind: "rejected", reason: "type", rules: RULES }),
      item("scan.pdf", { kind: "rejected", reason: "tooLarge", rules: RULES }, 21 * MIB),
      item("empty.md", { kind: "rejected", reason: "empty", rules: RULES }, 0),
    ]);

    expect(outcomeOf("timetable.docx")).toBe("Only .pdf, .md, and .txt files can be uploaded.");
    expect(outcomeOf("scan.pdf")).toBe("The file is larger than 20 MB.");
    expect(outcomeOf("empty.md")).toBe("The file is empty.");
  });

  it.each([
    ["duplicate_document", 409, "This file is already in the workspace."],
    [
      "unsupported_file_type",
      415,
      "The file could not be recognised as a PDF, Markdown or text file.",
    ],
    ["invalid_text_encoding", 422, "Markdown and text files must be saved in UTF-8."],
    [
      "storage_quota_exceeded",
      409,
      "Your files have used up your storage space. Delete some documents, then try again.",
    ],
    ["workspace_not_found", 404, "This workspace no longer exists."],
    ["internal_error", 500, "The file could not be uploaded. Try again."],
  ] as const)("says why the API refused a file with %s", (code, status, expected) => {
    renderResults([item("notes.md", refusedWith(code, status))]);

    expect(outcomeOf("notes.md")).toBe(expected);
    expect(screen.queryByText("The backend's own English.")).not.toBeInTheDocument();
  });

  it.each([
    [120, "Not sent. Try again in 2 minutes."],
    [60, "Not sent. Try again in 1 minute."],
    [30, "Not sent. Try again in 30 seconds."],
    [null, "Not sent. Try again in a moment."],
  ] as const)("names the wait of %s seconds for a file kept back", (seconds, expected) => {
    renderResults([item("notes.md", { kind: "notSent", retryAfterSeconds: seconds })]);

    expect(outcomeOf("notes.md")).toBe(expected);
  });

  it.each([
    [[uploading], "Uploading the file…"],
    [[uploaded, uploading, waiting], "Uploading file 2 of 3…"],
    [[refusedWith("duplicate_document"), waiting, uploading], "Uploading file 2 of 3…"],
    [
      [{ kind: "rejected", reason: "type", rules: RULES }, uploading, waiting],
      "Uploading file 1 of 2…",
    ],
    [[uploaded], "1 file uploaded."],
    [
      [uploaded, uploaded, { kind: "rejected", reason: "empty", rules: RULES }],
      "2 files uploaded. 1 file was not uploaded.",
    ],
    [[refusedWith("duplicate_document")], "1 file was not uploaded."],
    [
      [
        uploaded,
        refusedWith("rate_limited", 429),
        { kind: "notSent", retryAfterSeconds: 60 },
        { kind: "notSent", retryAfterSeconds: 60 },
      ],
      "1 file uploaded. 3 files were not uploaded.",
    ],
  ] as Array<[UploadState[], string]>)(
    "sums the files up in one polite live region: %#",
    (itemStates, summary) => {
      renderResults(itemStates.map((state, index) => item(`file-${index}.md`, state)));

      expect(screen.getAllByRole("status")).toHaveLength(1);
      expect(screen.getByRole("status")).toHaveTextContent(summary);
    },
  );

  it("offers to clear the list once nothing is left to upload", async () => {
    const onClear = vi.fn();
    renderResults([item("notes.md", uploaded)], "en", onClear);

    await userEvent.click(screen.getByRole("button", { name: "Clear upload results" }));

    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it("does not offer to clear the list while files upload", () => {
    renderResults([item("notes.md", uploaded), item("syllabus.txt", uploading)]);

    expect(screen.queryByRole("button", { name: "Clear upload results" })).not.toBeInTheDocument();
  });

  it("keeps a long name on one line and whole in its title", () => {
    const name = `${"organic-chemistry-".repeat(12)}week-5.md`;
    renderResults([item(name, uploaded)]);

    expect(screen.getByTitle(name)).toHaveClass("truncate");
    expect(screen.getByTitle(name)).toHaveTextContent(name);
  });

  it("shows a file name as text, whatever it contains", () => {
    const name = '<img src=x onerror="alert(1)">.md';
    renderResults([item(name, uploaded)]);

    expect(screen.getByTitle(name)).toHaveTextContent(name);
    expect(document.querySelector("img")).toBeNull();
  });

  it("speaks Russian", () => {
    renderResults(
      [
        item("timetable.docx", { kind: "rejected", reason: "type", rules: RULES }),
        item("scan.pdf", { kind: "rejected", reason: "tooLarge", rules: RULES }),
        item("notes.md", uploaded),
        item("outline.md", uploaded),
        item("draft.md", { kind: "notSent", retryAfterSeconds: 180 }),
      ],
      "ru",
    );

    expect(outcomeOf("timetable.docx")).toBe("Можно загружать только файлы .pdf, .md и .txt.");
    expect(outcomeOf("scan.pdf")).toBe("Файл больше 20 МБ.");
    expect(outcomeOf("notes.md")).toBe("Загружен");
    expect(outcomeOf("draft.md")).toBe("Не отправлен. Повторите через 3 минуты.");
    expect(screen.getByRole("status")).toHaveTextContent(
      "Загружено 2 файла. 3 файла не загружены.",
    );
    expect(screen.getByRole("list", { name: "Результаты загрузки" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Очистить результаты загрузки" }),
    ).toBeInTheDocument();
  });

  it.each([
    [[uploading, waiting, waiting, waiting, waiting], "Загружается файл 1 из 5…"],
    [[uploaded], "Загружен 1 файл."],
    [Array<UploadState>(21).fill(uploaded), "Загружен 21 файл."],
    [Array<UploadState>(5).fill(uploaded), "Загружено 5 файлов."],
    [[refusedWith("duplicate_document")], "1 файл не загружен."],
    [Array<UploadState>(5).fill(refusedWith("duplicate_document")), "5 файлов не загружено."],
  ] as Array<[UploadState[], string]>)(
    "sums the files up in Russian: %#",
    (itemStates, summary) => {
      renderResults(
        itemStates.map((state, index) => item(`file-${index}.md`, state)),
        "ru",
      );

      expect(screen.getByRole("status")).toHaveTextContent(summary);
    },
  );
});
