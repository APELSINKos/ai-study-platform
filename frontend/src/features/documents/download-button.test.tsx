import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Locale } from "@/i18n/config";
import { apiFetchBlob } from "@/lib/api/client";
import { ApiError, NETWORK_ERROR_CODE } from "@/lib/api/errors";
import type { DocumentOut } from "@/lib/api/types";
import { renderWithIntl } from "@/test/render";

import { DownloadButton } from "./download-button";
import { readyDocumentFixture } from "./test-fixtures";

vi.mock("@/lib/api/client", () => ({ apiFetch: vi.fn(), apiFetchBlob: vi.fn() }));

const apiFetchBlobMock = vi.mocked(apiFetchBlob);

const DOCUMENT = readyDocumentFixture(1);
const FILE_PATH = `/documents/${DOCUMENT.id}/file`;
const OBJECT_URL = "blob:http://localhost:3000/5f0c1f3e-0b6c-4f3b-9d0a-2a1f6c1e8b7d";

// jsdom has no object URLs, so the two functions are stood in for.
const createObjectURL = vi.fn<(file: Blob) => string>(() => OBJECT_URL);
const revokeObjectURL = vi.fn<(url: string) => void>();

interface Click {
  href: string;
  download: string;
  attached: boolean;
  revokedBefore: boolean;
  /** Whether the URL was revoked once the code that clicked had finished, before any timer. */
  revokedRightAfter: boolean;
}

/** Records the link clicks a download makes, instead of letting jsdom follow them. */
function captureClicks(): Click[] {
  const clicks: Click[] = [];
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    const click: Click = {
      href: this.href,
      download: this.download,
      attached: this.isConnected,
      revokedBefore: revokeObjectURL.mock.calls.length > 0,
      revokedRightAfter: false,
    };
    clicks.push(click);
    // A microtask runs as soon as the code that clicked returns, ahead of every timer.
    queueMicrotask(() => {
      click.revokedRightAfter = revokeObjectURL.mock.calls.length > 0;
    });
  });
  return clicks;
}

function renderButton(document: DocumentOut = DOCUMENT, locale: Locale = "en") {
  return renderWithIntl(<DownloadButton document={document} />, { locale });
}

describe("DownloadButton", () => {
  beforeEach(() => {
    apiFetchBlobMock.mockReset();
    createObjectURL.mockClear();
    revokeObjectURL.mockClear();
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      writable: true,
      value: createObjectURL,
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      writable: true,
      value: revokeObjectURL,
    });
  });

  afterEach(() => {
    Reflect.deleteProperty(URL, "createObjectURL");
    Reflect.deleteProperty(URL, "revokeObjectURL");
  });

  it("is a quiet button", () => {
    renderButton();

    expect(screen.getByRole("button", { name: "Download original" })).toHaveAttribute(
      "data-variant",
      "secondary",
    );
  });

  it("saves the file as it was uploaded, under its original name", async () => {
    const file = new Blob(["%PDF-1.7"], { type: "application/pdf" });
    apiFetchBlobMock.mockResolvedValue(file);
    const clicks = captureClicks();
    renderButton({ ...DOCUMENT, original_filename: "Лекция 4. Нормализация.pdf" });

    await userEvent.click(screen.getByRole("button", { name: "Download original" }));

    await waitFor(() => expect(clicks).toHaveLength(1));
    expect(apiFetchBlobMock).toHaveBeenCalledWith(FILE_PATH);
    expect(createObjectURL).toHaveBeenCalledWith(file);
    expect(clicks[0]).toEqual({
      href: OBJECT_URL,
      download: "Лекция 4. Нормализация.pdf",
      attached: true,
      revokedBefore: false,
      // Revoked later, not at once: revoking at once can cancel the download in some browsers.
      revokedRightAfter: false,
    });
    // The link was only a means to start the download.
    expect(document.querySelector("a")).toBeNull();
    await waitFor(() => expect(revokeObjectURL).toHaveBeenCalledWith(OBJECT_URL));
  });

  it("shows the button busy while the file is fetched, and fetches it once", async () => {
    apiFetchBlobMock.mockReturnValue(new Promise(() => {}));
    renderButton();
    const download = screen.getByRole("button", { name: "Download original" });

    await userEvent.click(download);
    await userEvent.click(download);

    expect(download).toHaveAttribute("aria-busy", "true");
    expect(apiFetchBlobMock).toHaveBeenCalledTimes(1);
  });

  it("says the stored file is gone", async () => {
    apiFetchBlobMock.mockRejectedValue(
      new ApiError({ status: 404, code: "document_file_missing", message: "File is missing." }),
    );
    const clicks = captureClicks();
    renderButton();

    await userEvent.click(screen.getByRole("button", { name: "Download original" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The original file is no longer stored.",
    );
    expect(screen.getByRole("alert")).toHaveClass("text-margin");
    expect(screen.queryByText("File is missing.")).not.toBeInTheDocument();
    expect(createObjectURL).not.toHaveBeenCalled();
    expect(clicks).toHaveLength(0);
  });

  it.each([
    [
      "a lost connection",
      new ApiError({ status: 0, code: NETWORK_ERROR_CODE, message: "x" }),
      "The API could not be reached. Check your connection and try again.",
    ],
    [
      "a server failure",
      new ApiError({ status: 500, code: "internal_error", message: "x" }),
      "The file could not be downloaded. Try again.",
    ],
  ])("reports %s and downloads on another try", async (_, failure, expected) => {
    apiFetchBlobMock
      .mockRejectedValueOnce(failure)
      .mockResolvedValueOnce(new Blob(["# Notes"], { type: "text/markdown" }));
    const clicks = captureClicks();
    renderButton();
    const download = screen.getByRole("button", { name: "Download original" });

    await userEvent.click(download);
    expect(await screen.findByRole("alert")).toHaveTextContent(expected);

    await userEvent.click(download);

    await waitFor(() => expect(clicks).toHaveLength(1));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("speaks Russian", async () => {
    apiFetchBlobMock.mockRejectedValue(
      new ApiError({ status: 404, code: "document_file_missing", message: "x" }),
    );
    renderButton(DOCUMENT, "ru");

    await userEvent.click(screen.getByRole("button", { name: "Скачать оригинал" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Исходный файл больше не хранится.");
  });
});
