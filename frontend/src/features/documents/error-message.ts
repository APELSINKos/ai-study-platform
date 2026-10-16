import type { useTranslations } from "next-intl";

import { WORKSPACE_NOT_FOUND_CODE } from "@/features/workspaces/error-message";
import { ApiError, NETWORK_ERROR_CODE } from "@/lib/api/errors";
import type { DocumentErrorCode } from "@/lib/api/types";

type DocumentErrorsTranslator = ReturnType<typeof useTranslations<"Documents.errors">>;
type ProcessingErrorsTranslator = ReturnType<typeof useTranslations<"Documents.processingErrors">>;

const SECONDS_PER_MINUTE = 60;

/** The answer for a document that does not exist or belongs to someone else. */
export const DOCUMENT_NOT_FOUND_CODE = "document_not_found";

/** The sentence for each reason processing can fail; a code the API adds breaks the build here. */
export const DOCUMENT_ERROR_MESSAGES = {
  pdf_unreadable: "pdfUnreadable",
  pdf_encrypted: "pdfEncrypted",
  no_text: "noText",
  too_many_pages: "tooManyPages",
  text_too_long: "textTooLong",
  file_missing: "fileMissing",
  ai_unavailable: "aiUnavailable",
  ai_quota_exceeded: "aiQuotaExceeded",
  ai_rejected: "aiRejected",
  ai_invalid_output: "aiInvalidOutput",
  embedding_dimension_mismatch: "embeddingDimensionMismatch",
  processing_timeout: "processingTimeout",
  queue_unavailable: "queueUnavailable",
  internal_error: "internalError",
} as const satisfies Record<DocumentErrorCode, string>;

/** Why a document could not be processed, translated. */
export function processingErrorMessage(
  code: DocumentErrorCode,
  t: ProcessingErrorsTranslator,
): string {
  return t(DOCUMENT_ERROR_MESSAGES[code]);
}

/** What the user was doing; it words the message when the failure has no wording of its own. */
export type DocumentAction = "load" | "loadMore" | "retry" | "delete";

const FAILED_ACTION_KEYS = {
  load: "loadFailed",
  loadMore: "loadMoreFailed",
  retry: "retryFailed",
  delete: "deleteFailed",
} as const satisfies Record<DocumentAction, string>;

function rateLimitedMessage(t: DocumentErrorsTranslator, retryAfterSeconds: number | null): string {
  if (retryAfterSeconds === null) {
    return t("rateLimitedGeneric");
  }
  if (retryAfterSeconds >= SECONDS_PER_MINUTE) {
    return t("rateLimitedMinutes", { minutes: Math.ceil(retryAfterSeconds / SECONDS_PER_MINUTE) });
  }
  return t("rateLimited", { seconds: retryAfterSeconds });
}

/** A translated sentence for a failed request about documents; the backend's English never shows. */
export function documentErrorMessage(
  error: unknown,
  action: DocumentAction,
  t: DocumentErrorsTranslator,
): string {
  if (error instanceof ApiError) {
    switch (error.code) {
      case NETWORK_ERROR_CODE:
        return t("networkError");
      case "csrf_failed":
        return t("csrfFailed");
      case "not_authenticated":
      case "token_expired":
      case "invalid_token":
        return t("sessionExpired");
      case WORKSPACE_NOT_FOUND_CODE:
        return t("workspaceNotFound");
      case DOCUMENT_NOT_FOUND_CODE:
        return t("documentNotFound");
      case "document_not_retryable":
        return t("notRetryable");
      case "rate_limited":
        return rateLimitedMessage(t, error.retryAfterSeconds);
      case "too_many_active_documents":
        return t("tooManyActive");
      case "storage_quota_exceeded":
        return t("storageQuotaExceeded");
    }
  }
  return t(FAILED_ACTION_KEYS[action]);
}
