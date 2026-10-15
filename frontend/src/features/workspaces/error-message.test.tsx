import { screen } from "@testing-library/react";
import { useTranslations } from "next-intl";
import { describe, expect, it } from "vitest";

import { ApiError, INVALID_RESPONSE_CODE, NETWORK_ERROR_CODE } from "@/lib/api/errors";
import { renderWithIntl } from "@/test/render";

import { workspaceErrorMessage, type WorkspaceAction } from "./error-message";

function Probe({ error, action }: { error: unknown; action: WorkspaceAction }) {
  const t = useTranslations("Workspaces.errors");
  return <p data-testid="message">{workspaceErrorMessage(error, action, t)}</p>;
}

function apiError(status: number, code: string): ApiError {
  return new ApiError({ status, code, message: "The backend's own English sentence." });
}

function messageFor(error: unknown, action: WorkspaceAction, locale: "en" | "ru" = "en"): string {
  renderWithIntl(<Probe error={error} action={action} />, { locale });
  return screen.getByTestId("message").textContent ?? "";
}

describe("workspaceErrorMessage", () => {
  it.each([
    [
      apiError(0, NETWORK_ERROR_CODE),
      "The API could not be reached. Check your connection and try again.",
    ],
    [apiError(422, "validation_error"), "Check the highlighted fields and try again."],
    [
      apiError(403, "csrf_failed"),
      "Your session could not be confirmed. Reload the page and try again.",
    ],
    [apiError(401, "not_authenticated"), "Your session has ended. Sign in again to continue."],
    [apiError(401, "token_expired"), "Your session has ended. Sign in again to continue."],
    [apiError(401, "invalid_token"), "Your session has ended. Sign in again to continue."],
  ])("names %o in its own words", (error, expected) => {
    expect(messageFor(error, "create")).toBe(expected);
  });

  it.each([
    ["load", "Your workspaces could not be loaded."],
    ["loadMore", "More workspaces could not be loaded."],
    ["create", "The workspace could not be created. Try again."],
  ] as const)("says what failed for any other error while trying to %s", (action, expected) => {
    expect(messageFor(apiError(500, "internal_error"), action)).toBe(expected);
  });

  it.each([
    [apiError(502, "http_error")],
    [apiError(200, INVALID_RESPONSE_CODE)],
    [new Error("boom")],
    ["not an error"],
  ])("falls back for %o", (error) => {
    expect(messageFor(error, "create")).toBe("The workspace could not be created. Try again.");
  });

  it("never shows the backend's English message", () => {
    expect(messageFor(apiError(500, "internal_error"), "load")).not.toContain("backend");
  });

  it("speaks Russian", () => {
    expect(messageFor(apiError(403, "csrf_failed"), "create", "ru")).toBe(
      "Не удалось подтвердить сеанс. Обновите страницу и попробуйте снова.",
    );
  });

  it("names the failed action in Russian", () => {
    expect(messageFor(apiError(500, "internal_error"), "create", "ru")).toBe(
      "Не удалось создать пространство. Попробуйте ещё раз.",
    );
  });
});
