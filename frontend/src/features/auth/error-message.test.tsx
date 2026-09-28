import { screen } from "@testing-library/react";
import { useTranslations } from "next-intl";
import { describe, expect, it } from "vitest";

import { ApiError, NETWORK_ERROR_CODE } from "@/lib/api/errors";
import { renderWithIntl } from "@/test/render";

import { authErrorMessage } from "./error-message";

function Probe({ error }: { error: unknown }) {
  const t = useTranslations("AuthErrors");
  return <p>{authErrorMessage(error, t)}</p>;
}

describe("authErrorMessage", () => {
  it("names a taken email", () => {
    renderWithIntl(
      <Probe error={new ApiError({ status: 409, code: "email_taken", message: "x" })} />,
    );

    expect(screen.getByText("An account with this email already exists.")).toBeInTheDocument();
  });

  it("names invalid credentials", () => {
    renderWithIntl(
      <Probe error={new ApiError({ status: 401, code: "invalid_credentials", message: "x" })} />,
    );

    expect(screen.getByText("Incorrect email or password.")).toBeInTheDocument();
  });

  it("includes the Retry-After seconds when the backend sent one", () => {
    renderWithIntl(
      <Probe
        error={
          new ApiError({ status: 429, code: "rate_limited", message: "x", retryAfterSeconds: 30 })
        }
      />,
    );

    expect(screen.getByText("Too many attempts. Try again in 30 seconds.")).toBeInTheDocument();
  });

  it("still uses seconds just under a minute", () => {
    renderWithIntl(
      <Probe
        error={
          new ApiError({ status: 429, code: "rate_limited", message: "x", retryAfterSeconds: 59 })
        }
      />,
    );

    expect(screen.getByText("Too many attempts. Try again in 59 seconds.")).toBeInTheDocument();
  });

  it("switches to minutes at 60 seconds", () => {
    renderWithIntl(
      <Probe
        error={
          new ApiError({ status: 429, code: "rate_limited", message: "x", retryAfterSeconds: 60 })
        }
      />,
    );

    expect(screen.getByText("Too many attempts. Try again in 1 minute.")).toBeInTheDocument();
  });

  it("rounds a partial minute up", () => {
    renderWithIntl(
      <Probe
        error={
          new ApiError({ status: 429, code: "rate_limited", message: "x", retryAfterSeconds: 61 })
        }
      />,
    );

    expect(screen.getByText("Too many attempts. Try again in 2 minutes.")).toBeInTheDocument();
  });

  it("rounds a long wait up to whole minutes", () => {
    renderWithIntl(
      <Probe
        error={
          new ApiError({
            status: 429,
            code: "rate_limited",
            message: "x",
            retryAfterSeconds: 3412,
          })
        }
      />,
    );

    expect(screen.getByText("Too many attempts. Try again in 57 minutes.")).toBeInTheDocument();
  });

  it("falls back to a generic rate-limit message without a Retry-After", () => {
    renderWithIntl(
      <Probe error={new ApiError({ status: 429, code: "rate_limited", message: "x" })} />,
    );

    expect(screen.getByText("Too many attempts. Try again in a moment.")).toBeInTheDocument();
  });

  it("names a validation error", () => {
    renderWithIntl(
      <Probe error={new ApiError({ status: 422, code: "validation_error", message: "x" })} />,
    );

    expect(screen.getByText("Check the highlighted fields and try again.")).toBeInTheDocument();
  });

  it("names a network error", () => {
    renderWithIntl(
      <Probe error={new ApiError({ status: 0, code: NETWORK_ERROR_CODE, message: "x" })} />,
    );

    expect(
      screen.getByText("The API could not be reached. Check your connection and try again."),
    ).toBeInTheDocument();
  });

  it("falls back for an unrecognised error code", () => {
    renderWithIntl(
      <Probe error={new ApiError({ status: 500, code: "http_error", message: "x" })} />,
    );

    expect(screen.getByText("Something went wrong. Please try again.")).toBeInTheDocument();
  });

  it("falls back for a value that is not an ApiError", () => {
    renderWithIntl(<Probe error={new Error("boom")} />);

    expect(screen.getByText("Something went wrong. Please try again.")).toBeInTheDocument();
  });

  it("speaks Russian when the interface does", () => {
    renderWithIntl(
      <Probe error={new ApiError({ status: 401, code: "invalid_credentials", message: "x" })} />,
      { locale: "ru" },
    );

    expect(screen.getByText("Неверный email или пароль.")).toBeInTheDocument();
  });

  it.each([
    [1, "Слишком много попыток. Повторите через 1 секунду."],
    [3, "Слишком много попыток. Повторите через 3 секунды."],
    [5, "Слишком много попыток. Повторите через 5 секунд."],
    [21, "Слишком много попыток. Повторите через 21 секунду."],
  ] as const)("pluralises %i second(s) in Russian", (seconds, expected) => {
    renderWithIntl(
      <Probe
        error={
          new ApiError({
            status: 429,
            code: "rate_limited",
            message: "x",
            retryAfterSeconds: seconds,
          })
        }
      />,
      { locale: "ru" },
    );

    expect(screen.getByText(expected)).toBeInTheDocument();
  });

  it.each([
    [60, "Слишком много попыток. Повторите через 1 минуту."],
    [180, "Слишком много попыток. Повторите через 3 минуты."],
    [300, "Слишком много попыток. Повторите через 5 минут."],
    [1260, "Слишком много попыток. Повторите через 21 минуту."],
  ] as const)("pluralises minutes in Russian for %i seconds", (seconds, expected) => {
    renderWithIntl(
      <Probe
        error={
          new ApiError({
            status: 429,
            code: "rate_limited",
            message: "x",
            retryAfterSeconds: seconds,
          })
        }
      />,
      { locale: "ru" },
    );

    expect(screen.getByText(expected)).toBeInTheDocument();
  });
});
