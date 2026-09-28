import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { renderWithIntl } from "@/test/render";

import { LoginForm } from "./login-form";

vi.mock("@/lib/api/client", () => ({ apiFetch: vi.fn() }));

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

const apiFetchMock = vi.mocked(apiFetch);

const SESSION = {
  user: { id: "1", email: "person@example.com", display_name: "Person", created_at: "2026-01-01" },
  access_token: "token",
  token_type: "bearer",
  expires_in: 900,
};

async function fillValidCredentials(): Promise<void> {
  await userEvent.type(screen.getByLabelText("Email"), "person@example.com");
  await userEvent.type(screen.getByLabelText("Password"), "correct horse battery");
}

function settle(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 20));
}

describe("LoginForm", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    replace.mockClear();
  });

  it("shows validation messages when submitted empty", async () => {
    renderWithIntl(<LoginForm />);

    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("Enter your email address.")).toBeInTheDocument();
    expect(screen.getByText("Enter your password.")).toBeInTheDocument();
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("shows Russian validation messages", async () => {
    renderWithIntl(<LoginForm />, { locale: "ru" });

    await userEvent.click(screen.getByRole("button", { name: "Войти" }));

    expect(await screen.findByText("Введите email.")).toBeInTheDocument();
    expect(screen.getByText("Введите пароль.")).toBeInTheDocument();
  });

  it("rejects a malformed email", async () => {
    renderWithIntl(<LoginForm />);

    await userEvent.type(screen.getByLabelText("Email"), "not-an-email");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("Enter a valid email address.")).toBeInTheDocument();
  });

  it("rejects a password longer than the backend maximum", async () => {
    renderWithIntl(<LoginForm />);

    await userEvent.type(screen.getByLabelText("Email"), "person@example.com");
    await userEvent.click(screen.getByLabelText("Password"));
    await userEvent.paste("x".repeat(129));
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("Password must be at most 128 characters.")).toBeInTheDocument();
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("shows its own wording when the server rejects a field", async () => {
    apiFetchMock.mockRejectedValue(
      new ApiError({
        status: 422,
        code: "validation_error",
        message: "x",
        details: [{ field: "email", message: "The domain name site.local is a special-use name." }],
      }),
    );
    renderWithIntl(<LoginForm />, { locale: "ru" });

    await userEvent.type(screen.getByLabelText("Email"), "person@site.local");
    await userEvent.type(screen.getByLabelText("Пароль"), "correct horse battery");
    await userEvent.click(screen.getByRole("button", { name: "Войти" }));

    expect(await screen.findByText("Введите корректный email.")).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toHaveAttribute("aria-invalid", "true");
    expect(screen.queryByText(/special-use/)).not.toBeInTheDocument();
  });

  it("navigates to a safe next on success", async () => {
    apiFetchMock.mockResolvedValue(SESSION);
    renderWithIntl(<LoginForm next="/dashboard?tab=progress" />);

    await fillValidCredentials();
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard?tab=progress"));
  });

  it.each([["https://evil.example"], ["//evil.example"], ["/\\evil"]])(
    "falls back to /dashboard for an unsafe next %s",
    async (next) => {
      apiFetchMock.mockResolvedValue(SESSION);
      renderWithIntl(<LoginForm next={next} />);

      await fillValidCredentials();
      await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

      await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
    },
  );

  it("shows the alert for invalid credentials", async () => {
    apiFetchMock.mockRejectedValue(
      new ApiError({ status: 401, code: "invalid_credentials", message: "x" }),
    );
    renderWithIntl(<LoginForm />);

    await fillValidCredentials();
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("Incorrect email or password.")).toHaveAttribute(
      "role",
      "alert",
    );
  });

  it("shows the wait time when rate limited", async () => {
    apiFetchMock.mockRejectedValue(
      new ApiError({ status: 429, code: "rate_limited", message: "x", retryAfterSeconds: 30 }),
    );
    renderWithIntl(<LoginForm />);

    await fillValidCredentials();
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(
      await screen.findByText("Too many attempts. Try again in 30 seconds."),
    ).toBeInTheDocument();
  });

  it("does not submit twice when the form is resubmitted while pending", async () => {
    apiFetchMock.mockImplementation(
      () => new Promise((resolve) => setTimeout(() => resolve(SESSION), 20)),
    );
    renderWithIntl(<LoginForm />);

    await fillValidCredentials();
    const form = screen.getByLabelText("Email").closest("form");
    expect(form).not.toBeNull();

    fireEvent.submit(form as HTMLFormElement);
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalledTimes(1));
    fireEvent.submit(form as HTMLFormElement);
    await settle();

    expect(apiFetchMock).toHaveBeenCalledTimes(1);
  });

  it("does not submit twice when the loading button is clicked again", async () => {
    apiFetchMock.mockImplementation(
      () => new Promise((resolve) => setTimeout(() => resolve(SESSION), 20)),
    );
    renderWithIntl(<LoginForm />);

    await fillValidCredentials();
    const button = screen.getByRole("button", { name: "Sign in" });
    await userEvent.click(button);
    expect(button).toHaveAttribute("aria-busy", "true");
    await userEvent.click(button);
    await settle();

    expect(apiFetchMock).toHaveBeenCalledTimes(1);
  });

  it("speaks Russian on the page labels", () => {
    renderWithIntl(<LoginForm />, { locale: "ru" });

    expect(screen.getByRole("heading", { name: "Вход" })).toBeInTheDocument();
    expect(screen.getByLabelText("Пароль")).toBeInTheDocument();
    expect(screen.getByText("Создать аккаунт")).toBeInTheDocument();
  });
});
