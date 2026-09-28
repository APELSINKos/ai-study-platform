import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { renderWithIntl } from "@/test/render";

import { RegisterForm } from "./register-form";

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

async function fillValidDetails(): Promise<void> {
  await userEvent.type(screen.getByLabelText("Name"), "Person");
  await userEvent.type(screen.getByLabelText("Email"), "person@example.com");
  await userEvent.type(screen.getByLabelText("Password"), "correct horse battery");
}

function settle(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 20));
}

describe("RegisterForm", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    replace.mockClear();
  });

  it("shows validation messages when submitted empty", async () => {
    renderWithIntl(<RegisterForm />);

    await userEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByText("Enter your name.")).toBeInTheDocument();
    expect(screen.getByText("Enter your email address.")).toBeInTheDocument();
    expect(screen.getByText("Password must be at least 10 characters.")).toBeInTheDocument();
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("shows a Russian validation message", async () => {
    renderWithIntl(<RegisterForm />, { locale: "ru" });

    await userEvent.click(screen.getByRole("button", { name: "Создать аккаунт" }));

    expect(await screen.findByText("Введите имя.")).toBeInTheDocument();
  });

  it("rejects a password shorter than the backend minimum", async () => {
    renderWithIntl(<RegisterForm />);

    await userEvent.type(screen.getByLabelText("Password"), "short");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByText("Password must be at least 10 characters.")).toBeInTheDocument();
  });

  it("navigates to a safe next on success", async () => {
    apiFetchMock.mockResolvedValue(SESSION);
    renderWithIntl(<RegisterForm next="/dashboard?tab=progress" />);

    await fillValidDetails();
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard?tab=progress"));
  });

  it("falls back to /dashboard for an unsafe next", async () => {
    apiFetchMock.mockResolvedValue(SESSION);
    renderWithIntl(<RegisterForm next="https://evil.example" />);

    await fillValidDetails();
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
  });

  it("puts a taken email on the email field", async () => {
    apiFetchMock.mockRejectedValue(
      new ApiError({ status: 409, code: "email_taken", message: "x" }),
    );
    renderWithIntl(<RegisterForm />);

    await fillValidDetails();
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));

    const email = screen.getByLabelText("Email");
    await waitFor(() => expect(email).toHaveAttribute("aria-invalid", "true"));
    expect(screen.getByText("An account with this email already exists.")).toBeInTheDocument();
    expect(email).toHaveFocus();
  });

  it("puts a server-side validation error on the matching field in its own wording", async () => {
    apiFetchMock.mockRejectedValue(
      new ApiError({
        status: 422,
        code: "validation_error",
        message: "x",
        details: [{ field: "display_name", message: "String should have at most 80 characters" }],
      }),
    );
    renderWithIntl(<RegisterForm />);

    await fillValidDetails();
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByText("Check this field.")).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("Name")).toHaveFocus();
    expect(screen.queryByText(/String should have/)).not.toBeInTheDocument();
    expect(
      screen.queryByText("Check the highlighted fields and try again."),
    ).not.toBeInTheDocument();
  });

  it("focuses only the first of several server-rejected fields", async () => {
    apiFetchMock.mockRejectedValue(
      new ApiError({
        status: 422,
        code: "validation_error",
        message: "x",
        details: [
          { field: "password", message: "x" },
          { field: "display_name", message: "x" },
        ],
      }),
    );
    renderWithIntl(<RegisterForm />);

    await fillValidDetails();
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() => expect(screen.getByLabelText("Password")).toHaveAttribute("aria-invalid"));
    expect(screen.getByLabelText("Password")).toHaveFocus();
    expect(screen.getByLabelText("Name")).not.toHaveFocus();
  });

  it("also shows the form alert when the server names a field the form does not have", async () => {
    apiFetchMock.mockRejectedValue(
      new ApiError({
        status: 422,
        code: "validation_error",
        message: "x",
        details: [
          { field: "password", message: "x" },
          { field: "invite_code", message: "x" },
        ],
      }),
    );
    renderWithIntl(<RegisterForm />);

    await fillValidDetails();
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByText("Check the highlighted fields and try again.")).toHaveAttribute(
      "role",
      "alert",
    );
    expect(screen.getByLabelText("Password")).toHaveAttribute("aria-invalid", "true");
  });

  it("does not submit twice when the form is resubmitted while pending", async () => {
    apiFetchMock.mockImplementation(
      () => new Promise((resolve) => setTimeout(() => resolve(SESSION), 20)),
    );
    renderWithIntl(<RegisterForm />);

    await fillValidDetails();
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
    renderWithIntl(<RegisterForm />);

    await fillValidDetails();
    const button = screen.getByRole("button", { name: "Create account" });
    await userEvent.click(button);
    expect(button).toHaveAttribute("aria-busy", "true");
    await userEvent.click(button);
    await settle();

    expect(apiFetchMock).toHaveBeenCalledTimes(1);
  });

  it("speaks Russian on the page labels", () => {
    renderWithIntl(<RegisterForm />, { locale: "ru" });

    expect(screen.getByRole("heading", { name: "Регистрация" })).toBeInTheDocument();
    expect(screen.getByLabelText("Имя")).toBeInTheDocument();
    expect(screen.getByText("Войти")).toBeInTheDocument();
  });
});
