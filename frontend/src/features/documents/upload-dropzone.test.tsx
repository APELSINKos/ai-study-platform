import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Locale } from "@/i18n/config";
import { apiFetch, type ApiRequestInit } from "@/lib/api/client";
import { ApiError, NETWORK_ERROR_CODE } from "@/lib/api/errors";
import type { DocumentOut, MetaOut } from "@/lib/api/types";
import { renderWithIntl } from "@/test/render";

import { WORKSPACE_ID, documentFixture } from "./test-fixtures";
import { UploadDropzone } from "./upload-dropzone";

vi.mock("@/lib/api/client", () => ({ apiFetch: vi.fn() }));

const apiFetchMock = vi.mocked(apiFetch);

const MIB = 1024 * 1024;
const META: MetaOut = {
  max_upload_bytes: 20 * MIB,
  allowed_extensions: [".pdf", ".md", ".txt"],
  max_pdf_pages: 500,
  max_active_documents_per_user: 10,
  max_storage_bytes_per_user: 1024 * MIB,
  ai: { mode: "offline", chat_model: "mock-heuristic-v1", embedding_model: "mock-hashing-v1" },
};
const UPLOAD_PATH = `/workspaces/${WORKSPACE_ID}/documents`;
const RULES_HINT = "You can upload .pdf, .md, and .txt files up to 20 MB each.";

function textFile(name: string, size?: number): File {
  const file = new File(["# Notes"], name);
  if (size !== undefined) {
    Object.defineProperty(file, "size", { value: size });
  }
  return file;
}

function sentFile(init: ApiRequestInit | undefined): string {
  const file = init?.body instanceof FormData ? init.body.get("file") : null;
  return file instanceof File ? file.name : "";
}

type UploadAnswer = (name: string) => Promise<DocumentOut>;

/** Answers GET /meta and uploads like the API would; either can be swapped for a test. */
function serve({
  meta = async () => META,
  upload = async (name: string) => documentFixture(1, { original_filename: name }),
}: { meta?: () => Promise<MetaOut>; upload?: UploadAnswer } = {}) {
  apiFetchMock.mockImplementation((path, init) => {
    if (path === "/meta") {
      return meta();
    }
    if (path === UPLOAD_PATH && init?.method === "POST") {
      return upload(sentFile(init));
    }
    return Promise.reject(new Error(`Unexpected request: ${path}`));
  });
}

/** The names of the files sent so far, in order. */
function sentNames(): string[] {
  return apiFetchMock.mock.calls
    .filter(([path]) => path === UPLOAD_PATH)
    .map(([, init]) => sentFile(init));
}

function renderZone(locale: Locale = "en") {
  return renderWithIntl(<UploadDropzone workspaceId={WORKSPACE_ID} />, { locale });
}

async function uploadButton(): Promise<HTMLElement> {
  const button = await screen.findByRole("button", { name: "Upload files" });
  await waitFor(() => expect(button).not.toHaveAttribute("aria-busy"));
  return button;
}

function zone(): HTMLElement {
  const element = document.querySelector<HTMLElement>("[data-dragging]");
  if (!element) {
    throw new Error("The drop zone is not on the page.");
  }
  return element;
}

function fileInput(): HTMLInputElement {
  const input = document.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) {
    throw new Error("The file input is not on the page.");
  }
  return input;
}

function dropFiles(target: Element, files: File[]): boolean {
  return fireEvent.drop(target, { dataTransfer: { files, types: ["Files"] } });
}

function dragFiles(type: "dragEnter" | "dragLeave", target: Element): void {
  fireEvent[type](target, { dataTransfer: { files: [], types: ["Files"] } });
}

/** What the row of a file says became of it. */
async function outcomeOf(name: string): Promise<string> {
  const row = (await screen.findByTitle(name)).closest("li");
  const outcome = row?.querySelector("[data-outcome]");
  if (!outcome) {
    throw new Error(`No outcome for ${name}.`);
  }
  return outcome.textContent ?? "";
}

function primaryActions(): string[] {
  return Array.from(document.querySelectorAll<HTMLElement>('[data-variant="primary"]')).map(
    (element) => element.textContent ?? "",
  );
}

describe("UploadDropzone", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it("shows Upload files busy while the upload limits load", async () => {
    serve({ meta: () => new Promise(() => {}) });
    renderZone();

    const button = screen.getByRole("button", { name: "Upload files" });
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(button).toHaveAttribute("data-variant", "primary");
    expect(screen.queryByText(RULES_HINT)).not.toBeInTheDocument();
    expect(document.querySelector('input[type="file"]')).toBeNull();

    expect(dropFiles(zone(), [textFile("notes.md")])).toBe(false);
    expect(sentNames()).toEqual([]);
  });

  it("states the limits from the API and offers a file picker limited to them", async () => {
    serve();
    renderZone();

    const button = await uploadButton();

    expect(screen.getByText(RULES_HINT)).toBeInTheDocument();
    expect(button).toHaveAccessibleDescription(RULES_HINT);
    expect(screen.getByText("or drag them here")).toBeInTheDocument();
    const input = fileInput();
    expect(input).toHaveAttribute("accept", ".pdf,.md,.txt");
    expect(input).toHaveAttribute("multiple");
    expect(input).not.toBeVisible();
    expect(primaryActions()).toEqual(["Upload files"]);
  });

  it("opens the file picker from the keyboard and uploads the chosen files", async () => {
    serve();
    renderZone();
    const button = await uploadButton();
    const openPicker = vi.spyOn(fileInput(), "click");

    await userEvent.tab();
    expect(button).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(openPicker).toHaveBeenCalledTimes(1);

    await userEvent.upload(fileInput(), [textFile("notes.md"), textFile("syllabus.txt")]);

    expect(await outcomeOf("notes.md")).toBe("Uploaded");
    await waitFor(async () => expect(await outcomeOf("syllabus.txt")).toBe("Uploaded"));
    expect(sentNames()).toEqual(["notes.md", "syllabus.txt"]);
    expect(apiFetchMock).toHaveBeenCalledWith(UPLOAD_PATH, {
      method: "POST",
      body: expect.any(FormData),
    });
  });

  it("clears the picker after each choice, so the same file can be chosen again", async () => {
    serve();
    renderZone();
    await uploadButton();
    const notes = textFile("notes.md");

    await userEvent.upload(fileInput(), notes);
    expect(fileInput().value).toBe("");
    await waitFor(() => expect(sentNames()).toEqual(["notes.md"]));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("1 file uploaded."));

    await userEvent.upload(fileInput(), notes);

    await waitFor(() => expect(sentNames()).toEqual(["notes.md", "notes.md"]));
  });

  it("uploads files dropped on the zone", async () => {
    serve();
    renderZone();
    await uploadButton();

    expect(dropFiles(zone(), [textFile("notes.md")])).toBe(false);

    expect(await outcomeOf("notes.md")).toBe("Uploaded");
    expect(sentNames()).toEqual(["notes.md"]);
  });

  it("turns down files that break the limits and never sends them", async () => {
    serve();
    renderZone();
    await uploadButton();

    dropFiles(zone(), [
      textFile("timetable.docx"),
      textFile("empty.md", 0),
      textFile("scan.pdf", 21 * MIB),
    ]);

    expect(await outcomeOf("timetable.docx")).toBe(
      "Only .pdf, .md, and .txt files can be uploaded.",
    );
    expect(await outcomeOf("empty.md")).toBe("The file is empty.");
    expect(await outcomeOf("scan.pdf")).toBe("The file is larger than 20 MB.");
    expect(screen.getByRole("status")).toHaveTextContent("3 files were not uploaded.");
    expect(sentNames()).toEqual([]);
  });

  it("marks the zone while files are dragged over it, wherever the pointer is inside", async () => {
    serve();
    renderZone();
    const button = await uploadButton();

    dragFiles("dragEnter", zone());
    expect(zone()).toHaveAttribute("data-dragging", "true");
    expect(screen.getByText("Drop the files to upload them")).toBeInTheDocument();

    // Moving onto the button enters it before the zone is left.
    dragFiles("dragEnter", button);
    dragFiles("dragLeave", zone());
    expect(zone()).toHaveAttribute("data-dragging", "true");

    dragFiles("dragLeave", button);
    expect(zone()).toHaveAttribute("data-dragging", "false");
    expect(screen.getByText("or drag them here")).toBeInTheDocument();

    dragFiles("dragEnter", zone());
    dropFiles(zone(), [textFile("notes.md")]);
    expect(zone()).toHaveAttribute("data-dragging", "false");
  });

  it("takes files dragged over the zone", async () => {
    serve();
    renderZone();
    await uploadButton();
    const dataTransfer = { files: [], types: ["Files"], dropEffect: "none" };

    expect(fireEvent.dragOver(zone(), { dataTransfer })).toBe(false);
    expect(dataTransfer.dropEffect).toBe("copy");
  });

  it("leaves dragged text alone", async () => {
    serve();
    renderZone();
    await uploadButton();
    const text = { dataTransfer: { files: [], types: ["text/plain"] } };

    fireEvent.dragEnter(zone(), text);
    expect(zone()).toHaveAttribute("data-dragging", "false");
    expect(fireEvent.dragOver(zone(), text)).toBe(true);
    expect(fireEvent.drop(zone(), text)).toBe(true);
    expect(fireEvent.dragOver(document.body, text)).toBe(true);
  });

  it("keeps files dropped beside the zone from opening in the browser", async () => {
    serve();
    const { unmount } = renderZone();
    await uploadButton();
    const dataTransfer = { files: [textFile("notes.md")], types: ["Files"], dropEffect: "copy" };

    expect(fireEvent.dragOver(document.body, { dataTransfer })).toBe(false);
    expect(dataTransfer.dropEffect).toBe("none");
    expect(fireEvent.drop(document.body, { dataTransfer })).toBe(false);
    expect(sentNames()).toEqual([]);

    unmount();
    expect(fireEvent.drop(document.body, { dataTransfer })).toBe(true);
  });

  it("shows Upload files busy during a run and sends files dropped meanwhile after it", async () => {
    const answers: Array<() => void> = [];
    serve({
      upload: (name) =>
        new Promise((resolve) => {
          answers.push(() => resolve(documentFixture(1, { original_filename: name })));
        }),
    });
    renderZone();
    const button = await uploadButton();

    dropFiles(zone(), [textFile("a.md")]);
    await waitFor(() => expect(button).toHaveAttribute("aria-busy", "true"));
    dropFiles(zone(), [textFile("b.md")]);

    expect(await outcomeOf("a.md")).toBe("Uploading…");
    expect(await outcomeOf("b.md")).toBe("Waiting");
    expect(screen.getByRole("status")).toHaveTextContent("Uploading file 1 of 2…");
    expect(sentNames()).toEqual(["a.md"]);

    answers.shift()?.();
    await waitFor(() => expect(sentNames()).toEqual(["a.md", "b.md"]));
    answers.shift()?.();

    await waitFor(() => expect(button).not.toHaveAttribute("aria-busy"));
    expect(screen.getByRole("status")).toHaveTextContent("2 files uploaded.");
  });

  it("keeps the files left unsent once uploads are rate limited", async () => {
    let uploads = 0;
    serve({
      upload: async (name) => {
        uploads += 1;
        if (uploads === 2) {
          throw new ApiError({
            status: 429,
            code: "rate_limited",
            message: "Too many requests.",
            retryAfterSeconds: 120,
          });
        }
        return documentFixture(uploads, { original_filename: name });
      },
    });
    renderZone();
    await uploadButton();

    dropFiles(zone(), [textFile("a.md"), textFile("b.md"), textFile("c.md")]);

    await waitFor(async () =>
      expect(await outcomeOf("c.md")).toBe("Not sent. Try again in 2 minutes."),
    );
    expect(await outcomeOf("a.md")).toBe("Uploaded");
    expect(await outcomeOf("b.md")).toBe("Too many attempts. Try again in 2 minutes.");
    expect(sentNames()).toEqual(["a.md", "b.md"]);
    expect(screen.getByRole("status")).toHaveTextContent(
      "1 file uploaded. 2 files were not uploaded.",
    );
  });

  it("clears the results and gives the focus back to Upload files", async () => {
    serve();
    renderZone();
    const button = await uploadButton();
    dropFiles(zone(), [textFile("notes.md")]);

    await userEvent.click(await screen.findByRole("button", { name: "Clear upload results" }));

    expect(screen.queryByRole("list", { name: "Upload results" })).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    expect(button).toHaveFocus();
  });

  it.each([
    [
      "a server failure",
      new ApiError({ status: 503, code: "http_error", message: "Service Unavailable" }),
      "The upload limits could not be loaded.",
    ],
    [
      "a lost connection",
      new ApiError({ status: 0, code: NETWORK_ERROR_CODE, message: "x" }),
      "The API could not be reached. Check your connection and try again.",
    ],
  ])("reports %s while loading the limits and loads them on request", async (_, failure, text) => {
    let attempts = 0;
    serve({
      meta: async () => {
        attempts += 1;
        if (attempts === 1) {
          throw failure;
        }
        return META;
      },
    });
    renderZone();

    expect(await screen.findByRole("alert")).toHaveTextContent(text);
    expect(screen.queryByRole("button", { name: "Upload files" })).not.toBeInTheDocument();
    expect(primaryActions()).toEqual([]);
    const retry = screen.getByRole("button", { name: "Try again" });
    expect(retry).toHaveAttribute("data-variant", "secondary");

    await userEvent.click(retry);

    const button = await screen.findByRole("button", { name: "Upload files" });
    await waitFor(() => expect(button).toHaveFocus());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText(RULES_HINT)).toBeInTheDocument();
  });

  it("speaks Russian", async () => {
    serve();
    renderZone("ru");

    const button = await screen.findByRole("button", { name: "Загрузить файлы" });
    await waitFor(() => expect(button).not.toHaveAttribute("aria-busy"));
    expect(screen.getByText("или перетащите их сюда")).toBeInTheDocument();
    expect(
      screen.getByText("Можно загружать файлы .pdf, .md и .txt размером до 20 МБ."),
    ).toBeInTheDocument();

    dropFiles(zone(), [textFile("notes.md")]);

    const list = await screen.findByRole("list", { name: "Результаты загрузки" });
    expect(await within(list).findByText("Загружен")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Загружен 1 файл.");
  });
});
