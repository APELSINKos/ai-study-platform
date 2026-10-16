import { screen } from "@testing-library/react";
import { useTranslations } from "next-intl";
import { describe, expect, it } from "vitest";

import type { Locale } from "@/i18n/config";
import {
  ApiError,
  HTTP_ERROR_CODE,
  INVALID_RESPONSE_CODE,
  NETWORK_ERROR_CODE,
} from "@/lib/api/errors";
import type { DocumentErrorCode } from "@/lib/api/types";
import { renderWithIntl } from "@/test/render";

import {
  DOCUMENT_ERROR_MESSAGES,
  documentErrorMessage,
  processingErrorMessage,
  waitOf,
  type DocumentAction,
} from "./error-message";

function ProcessingProbe({ code }: { code: DocumentErrorCode }) {
  const t = useTranslations("Documents.processingErrors");
  return <p>{processingErrorMessage(code, t)}</p>;
}

function RequestProbe({ error, action }: { error: unknown; action: DocumentAction }) {
  const t = useTranslations("Documents.errors");
  return <p>{documentErrorMessage(error, action, t)}</p>;
}

function sentenceFor(code: DocumentErrorCode, locale: Locale = "en"): string {
  const { unmount } = renderWithIntl(<ProcessingProbe code={code} />, { locale });
  const text = screen.getByRole("paragraph").textContent ?? "";
  unmount();
  return text;
}

function messageFor(error: unknown, action: DocumentAction = "load", locale: Locale = "en") {
  const { unmount } = renderWithIntl(<RequestProbe error={error} action={action} />, { locale });
  const text = screen.getByRole("paragraph").textContent ?? "";
  unmount();
  return text;
}

function apiError(status: number, code: string, retryAfterSeconds: number | null = null) {
  return new ApiError({ status, code, message: "The backend's own English.", retryAfterSeconds });
}

describe("processingErrorMessage", () => {
  it("has a sentence for every reason processing can fail", () => {
    expect(Object.keys(DOCUMENT_ERROR_MESSAGES).sort()).toEqual([
      "ai_invalid_output",
      "ai_quota_exceeded",
      "ai_rejected",
      "ai_unavailable",
      "embedding_dimension_mismatch",
      "file_missing",
      "internal_error",
      "no_text",
      "pdf_encrypted",
      "pdf_unreadable",
      "processing_timeout",
      "queue_unavailable",
      "text_too_long",
      "too_many_pages",
    ]);
  });

  it("gives every reason a sentence of its own in both languages", () => {
    const codes = Object.keys(DOCUMENT_ERROR_MESSAGES) as DocumentErrorCode[];
    for (const locale of ["en", "ru"] as const) {
      const sentences = codes.map((code) => sentenceFor(code, locale));
      expect(new Set(sentences).size).toBe(codes.length);
      for (const sentence of sentences) {
        expect(sentence).toMatch(/\.$/);
      }
    }
  });

  it.each([
    ["pdf_unreadable", "The PDF could not be read. The file may be damaged."],
    ["no_text", "No text was found in the file. A scanned PDF needs a text layer."],
    ["text_too_long", "The file holds too much text. Split it into smaller files."],
    ["queue_unavailable", "The file could not be queued for processing."],
    ["internal_error", "Something went wrong while the file was processed."],
  ] as const)("says what %s means", (code, expected) => {
    expect(sentenceFor(code)).toBe(expected);
  });

  it.each([
    ["pdf_unreadable", "Не удалось прочитать PDF. Возможно, файл повреждён."],
    ["no_text", "В файле не найден текст. У отсканированного PDF должен быть текстовый слой."],
    ["pdf_encrypted", "PDF защищён паролем. Загрузите копию без пароля."],
  ] as const)("says what %s means in Russian", (code, expected) => {
    expect(sentenceFor(code, "ru")).toBe(expected);
  });
});

describe("documentErrorMessage", () => {
  it("asks to check the connection when the API cannot be reached", () => {
    expect(messageFor(apiError(0, NETWORK_ERROR_CODE))).toBe(
      "The API could not be reached. Check your connection and try again.",
    );
  });

  it("asks to reload when the session could not be confirmed", () => {
    expect(messageFor(apiError(403, "csrf_failed"))).toBe(
      "Your session could not be confirmed. Reload the page and try again.",
    );
  });

  it.each(["not_authenticated", "token_expired", "invalid_token"])(
    "asks to sign in again after %s",
    (code) => {
      expect(messageFor(apiError(401, code))).toBe(
        "Your session has ended. Sign in again to continue.",
      );
    },
  );

  it("says the workspace is gone", () => {
    expect(messageFor(apiError(404, "workspace_not_found"))).toBe(
      "This workspace no longer exists.",
    );
  });

  it.each([
    [30, "Too many attempts. Try again in 30 seconds."],
    [59, "Too many attempts. Try again in 59 seconds."],
    [60, "Too many attempts. Try again in 1 minute."],
    [61, "Too many attempts. Try again in 2 minutes."],
    [1800, "Too many attempts. Try again in 30 minutes."],
  ] as const)("names the wait of %i seconds when rate limited", (seconds, expected) => {
    expect(messageFor(apiError(429, "rate_limited", seconds))).toBe(expected);
  });

  it("falls back to a moment when a rate limit names no wait", () => {
    expect(messageFor(apiError(429, "rate_limited"))).toBe(
      "Too many attempts. Try again in a moment.",
    );
  });

  it("says too many files are being processed at once", () => {
    expect(messageFor(apiError(429, "too_many_active_documents", 60))).toBe(
      "Too many of your files are being processed right now. Try again once some of them are ready.",
    );
  });

  it("says the storage space is used up", () => {
    expect(messageFor(apiError(409, "storage_quota_exceeded"))).toBe(
      "Your files have used up your storage space. Delete some documents, then try again.",
    );
  });

  it("says the document is gone", () => {
    expect(messageFor(apiError(404, "document_not_found"), "retry")).toBe(
      "This document no longer exists.",
    );
  });

  it("says a document already on its way cannot be retried", () => {
    expect(messageFor(apiError(409, "document_not_retryable"), "retry")).toBe(
      "This document is already being processed.",
    );
  });

  it.each([
    ["duplicate_document", 409, "This file is already in the workspace."],
    ["payload_too_large", 413, "The file is larger than the upload limit."],
    [
      "unsupported_file_type",
      415,
      "The file could not be recognised as a PDF, Markdown or text file.",
    ],
    ["invalid_text_encoding", 422, "Markdown and text files must be saved in UTF-8."],
    ["empty_file", 422, "The file is empty."],
  ] as const)("says why an upload was refused with %s", (code, status, expected) => {
    expect(messageFor(apiError(status, code), "upload")).toBe(expected);
  });

  it.each([
    ["bad_request", 400],
    ["validation_error", 422],
    ["internal_error", 500],
    [HTTP_ERROR_CODE, 502],
    [INVALID_RESPONSE_CODE, 200],
    ["something_new", 418],
  ] as const)("words %s by what the user was doing", (code, status) => {
    expect(messageFor(apiError(status, code), "load")).toBe("The documents could not be loaded.");
    expect(messageFor(apiError(status, code), "loadMore")).toBe(
      "More documents could not be loaded.",
    );
    expect(messageFor(apiError(status, code), "retry")).toBe(
      "Processing could not be started again. Try again.",
    );
    expect(messageFor(apiError(status, code), "delete")).toBe(
      "The document could not be deleted. Try again.",
    );
    expect(messageFor(apiError(status, code), "upload")).toBe(
      "The file could not be uploaded. Try again.",
    );
    expect(messageFor(apiError(status, code), "loadLimits")).toBe(
      "The upload limits could not be loaded.",
    );
  });

  it("words a failure that is no API error by what the user was doing", () => {
    expect(messageFor(new Error("boom"))).toBe("The documents could not be loaded.");
  });

  it("never shows the backend's English", () => {
    messageFor(apiError(500, "internal_error"));

    expect(screen.queryByText("The backend's own English.")).not.toBeInTheDocument();
  });

  it.each([
    [1, "Слишком много попыток. Повторите через 1 секунду."],
    [3, "Слишком много попыток. Повторите через 3 секунды."],
    [5, "Слишком много попыток. Повторите через 5 секунд."],
    [180, "Слишком много попыток. Повторите через 3 минуты."],
    [1260, "Слишком много попыток. Повторите через 21 минуту."],
  ] as const)("names a wait of %i seconds in Russian", (seconds, expected) => {
    expect(messageFor(apiError(429, "rate_limited", seconds), "load", "ru")).toBe(expected);
  });

  it("speaks Russian", () => {
    expect(messageFor(apiError(404, "workspace_not_found"), "load", "ru")).toBe(
      "Этого пространства больше нет.",
    );
    expect(messageFor(apiError(500, "internal_error"), "loadMore", "ru")).toBe(
      "Не удалось загрузить остальные документы.",
    );
    expect(messageFor(apiError(409, "document_not_retryable"), "retry", "ru")).toBe(
      "Этот документ уже обрабатывается.",
    );
    expect(messageFor(apiError(500, "internal_error"), "delete", "ru")).toBe(
      "Не удалось удалить документ. Попробуйте ещё раз.",
    );
    expect(messageFor(apiError(409, "duplicate_document"), "upload", "ru")).toBe(
      "Этот файл уже есть в пространстве.",
    );
    expect(messageFor(apiError(422, "invalid_text_encoding"), "upload", "ru")).toBe(
      "Файлы Markdown и текстовые файлы должны быть сохранены в UTF-8.",
    );
    expect(messageFor(apiError(500, "internal_error"), "upload", "ru")).toBe(
      "Не удалось загрузить файл. Попробуйте ещё раз.",
    );
    expect(messageFor(apiError(503, "http_error"), "loadLimits", "ru")).toBe(
      "Не удалось получить ограничения на загрузку файлов.",
    );
  });
});

describe("waitOf", () => {
  it.each([
    [null, null],
    [1, { seconds: 1 }],
    [59, { seconds: 59 }],
    [60, { minutes: 1 }],
    [61, { minutes: 2 }],
    [3600, { minutes: 60 }],
  ] as const)("reads a wait of %s seconds as %j", (seconds, expected) => {
    expect(waitOf(seconds)).toEqual(expected);
  });
});
