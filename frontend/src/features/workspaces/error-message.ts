import type { useTranslations } from "next-intl";

import { ApiError, NETWORK_ERROR_CODE } from "@/lib/api/errors";

type WorkspaceErrorsTranslator = ReturnType<typeof useTranslations<"Workspaces.errors">>;

/** What the user was doing; it words the message when the failure has no wording of its own. */
export type WorkspaceAction = "load" | "loadMore";

const FAILED_ACTION_KEYS = {
  load: "loadFailed",
  loadMore: "loadMoreFailed",
} as const satisfies Record<WorkspaceAction, string>;

/** A translated sentence for a failed workspace request; the backend's English never shows. */
export function workspaceErrorMessage(
  error: unknown,
  action: WorkspaceAction,
  t: WorkspaceErrorsTranslator,
): string {
  if (error instanceof ApiError) {
    switch (error.code) {
      case NETWORK_ERROR_CODE:
        return t("networkError");
      case "not_authenticated":
      case "token_expired":
      case "invalid_token":
        return t("sessionExpired");
    }
  }
  return t(FAILED_ACTION_KEYS[action]);
}
