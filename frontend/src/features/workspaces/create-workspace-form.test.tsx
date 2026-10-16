import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "@/lib/api/client";
import { ApiError, NETWORK_ERROR_CODE } from "@/lib/api/errors";
import { renderWithIntl } from "@/test/render";

import { CreateWorkspaceForm } from "./create-workspace-form";
import { workspaceFixture } from "./test-fixtures";

vi.mock("@/lib/api/client", () => ({ apiFetch: vi.fn() }));

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const apiFetchMock = vi.mocked(apiFetch);

const CREATED = workspaceFixture(7, { name: "Organic chemistry" });

function submit(name = "Create workspace"): Promise<void> {
  return userEvent.click(screen.getByRole("button", { name }));
}

async function pasteInto(label: string, text: string): Promise<void> {
  await userEvent.click(screen.getByLabelText(label));
  await userEvent.paste(text);
}

describe("CreateWorkspaceForm", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    push.mockClear();
  });

  it("asks for a name before sending anything", async () => {
    renderWithIntl(<CreateWorkspaceForm />);

    await userEvent.type(screen.getByLabelText("Name"), "   ");
    await submit();

    expect(await screen.findByText("Enter a name.")).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveFocus();
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("rejects a name longer than the server keeps", async () => {
    renderWithIntl(<CreateWorkspaceForm />);

    await pasteInto("Name", "x".repeat(121));
    await submit();

    expect(await screen.findByText("Name must be at most 120 characters.")).toBeInTheDocument();
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("counts characters the way the server does, so 120 emoji still fit", async () => {
    apiFetchMock.mockResolvedValue(CREATED);
    renderWithIntl(<CreateWorkspaceForm />);

    await pasteInto("Name", "📚".repeat(120));
    await submit();

    await waitFor(() => expect(apiFetchMock).toHaveBeenCalledTimes(1));
  });

  it("rejects a description longer than the server keeps", async () => {
    renderWithIntl(<CreateWorkspaceForm />);

    await userEvent.type(screen.getByLabelText("Name"), "Organic chemistry");
    await pasteInto("Description", "x".repeat(1001));
    await submit();

    expect(
      await screen.findByText("Description must be at most 1,000 characters."),
    ).toBeInTheDocument();
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("asks to finish a half-typed exam date instead of dropping it", async () => {
    renderWithIntl(<CreateWorkspaceForm />);
    await userEvent.type(screen.getByLabelText("Name"), "Organic chemistry");
    const examDate = screen.getByLabelText("Exam date");
    // A browser reports a partly filled date input as empty and flags it as bad input.
    Object.defineProperty(examDate, "validity", { configurable: true, value: { badInput: true } });

    await submit();

    expect(
      await screen.findByText("Enter the whole date, or clear the field."),
    ).toBeInTheDocument();
    expect(examDate).toHaveFocus();
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("flags a half-typed exam date together with the other mistakes", async () => {
    renderWithIntl(<CreateWorkspaceForm />);
    const examDate = screen.getByLabelText("Exam date");
    Object.defineProperty(examDate, "validity", { configurable: true, value: { badInput: true } });

    await submit();

    expect(await screen.findByText("Enter a name.")).toBeInTheDocument();
    expect(screen.getByText("Enter the whole date, or clear the field.")).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveFocus();
  });

  it("creates a workspace without the optional fields and opens it", async () => {
    apiFetchMock.mockResolvedValue(CREATED);
    renderWithIntl(<CreateWorkspaceForm />);

    await userEvent.type(screen.getByLabelText("Name"), "  Organic chemistry  ");
    await submit();

    await waitFor(() => expect(push).toHaveBeenCalledWith(`/workspaces/${CREATED.id}`));
    expect(apiFetchMock).toHaveBeenCalledWith("/workspaces", {
      method: "POST",
      json: { name: "Organic chemistry", description: null, exam_date: null },
    });
  });

  it("sends the description and the exam date", async () => {
    apiFetchMock.mockResolvedValue(CREATED);
    renderWithIntl(<CreateWorkspaceForm />);

    await userEvent.type(screen.getByLabelText("Name"), "Organic chemistry");
    await userEvent.type(screen.getByLabelText("Description"), "  Chapters 1 to 6  ");
    fireEvent.change(screen.getByLabelText("Exam date"), { target: { value: "2026-10-28" } });
    await submit();

    await waitFor(() =>
      expect(apiFetchMock).toHaveBeenCalledWith("/workspaces", {
        method: "POST",
        json: {
          name: "Organic chemistry",
          description: "Chapters 1 to 6",
          exam_date: "2026-10-28",
        },
      }),
    );
  });

  it("leaves a user who has moved on where they went once the workspace exists", async () => {
    const creation = Promise.withResolvers<typeof CREATED>();
    apiFetchMock.mockReturnValue(creation.promise);
    const { queryClient, unmount } = renderWithIntl(<CreateWorkspaceForm />);
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    await userEvent.type(screen.getByLabelText("Name"), "Organic chemistry");
    await submit();
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalledTimes(1));

    unmount();
    creation.resolve(CREATED);

    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["workspaces"] }));
    expect(push).not.toHaveBeenCalled();
  });

  it("refreshes every workspace list once the workspace exists", async () => {
    apiFetchMock.mockResolvedValue(CREATED);
    const { queryClient } = renderWithIntl(<CreateWorkspaceForm />);
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    await userEvent.type(screen.getByLabelText("Name"), "Organic chemistry");
    await submit();

    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["workspaces"] }));
  });

  it("points at a field the server rejected, in its own words", async () => {
    apiFetchMock.mockRejectedValue(
      new ApiError({
        status: 422,
        code: "validation_error",
        message: "The request contains invalid data.",
        details: [{ field: "exam_date", message: "Input should be a valid date" }],
      }),
    );
    renderWithIntl(<CreateWorkspaceForm />);

    await userEvent.type(screen.getByLabelText("Name"), "Organic chemistry");
    await submit();

    expect(await screen.findByText("Check this field.")).toBeInTheDocument();
    const examDate = screen.getByLabelText("Exam date");
    expect(examDate).toHaveAttribute("aria-invalid", "true");
    expect(examDate).toHaveFocus();
    expect(screen.queryByText(/valid date|invalid data/)).not.toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it.each([
    [
      new ApiError({ status: 0, code: NETWORK_ERROR_CODE, message: "x" }),
      "The API could not be reached. Check your connection and try again.",
    ],
    [
      new ApiError({ status: 403, code: "csrf_failed", message: "x" }),
      "Your session could not be confirmed. Reload the page and try again.",
    ],
    [
      new ApiError({ status: 500, code: "internal_error", message: "x" }),
      "The workspace could not be created. Try again.",
    ],
  ])("explains a failure to create (%o)", async (error, expected) => {
    apiFetchMock.mockRejectedValue(error);
    renderWithIntl(<CreateWorkspaceForm />);

    await userEvent.type(screen.getByLabelText("Name"), "Organic chemistry");
    await submit();

    expect(await screen.findByText(expected)).toHaveAttribute("role", "alert");
    expect(screen.getByRole("button", { name: "Create workspace" })).not.toHaveAttribute(
      "aria-busy",
    );
    expect(push).not.toHaveBeenCalled();
  });

  it("sends one request however often it is submitted, and stays busy until the page changes", async () => {
    apiFetchMock.mockImplementation(
      () => new Promise((resolve) => setTimeout(() => resolve(CREATED), 20)),
    );
    renderWithIntl(<CreateWorkspaceForm />);
    await userEvent.type(screen.getByLabelText("Name"), "Organic chemistry");
    const button = screen.getByRole("button", { name: "Create workspace" });

    await userEvent.click(button);
    await userEvent.click(button);
    fireEvent.submit(button.closest("form") as HTMLFormElement);
    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    await userEvent.click(button);

    expect(button).toHaveAttribute("aria-busy", "true");
    expect(apiFetchMock).toHaveBeenCalledTimes(1);
  });

  it("offers Cancel only when there is somewhere to return to", async () => {
    const onCancel = vi.fn();
    const { unmount } = renderWithIntl(<CreateWorkspaceForm onCancel={onCancel} />);

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    unmount();

    renderWithIntl(<CreateWorkspaceForm />);
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
  });

  it("puts the cursor in the name field only when asked to", () => {
    const { unmount } = renderWithIntl(<CreateWorkspaceForm autoFocus />);
    expect(screen.getByLabelText("Name")).toHaveFocus();
    unmount();

    renderWithIntl(<CreateWorkspaceForm />);
    expect(screen.getByLabelText("Name")).not.toHaveFocus();
  });

  it("is a named form whose optional fields say so", () => {
    renderWithIntl(<CreateWorkspaceForm />);

    expect(screen.getByRole("form", { name: "New workspace" })).toBeInTheDocument();
    expect(screen.getByLabelText("Description")).toHaveAccessibleDescription(
      "Optional. What the course or the exam covers.",
    );
    expect(screen.getByLabelText("Exam date")).toHaveAccessibleDescription(
      "Optional. Recall counts down the days to it.",
    );
  });

  it("speaks Russian", async () => {
    renderWithIntl(<CreateWorkspaceForm onCancel={() => {}} />, { locale: "ru" });

    expect(screen.getByRole("heading", { name: "Новое пространство" })).toBeInTheDocument();
    expect(screen.getByLabelText("Дата экзамена")).toHaveAttribute("type", "date");
    expect(screen.getByRole("button", { name: "Отмена" })).toBeInTheDocument();

    await pasteInto("Описание", "x".repeat(1001));
    await submit("Создать пространство");

    expect(await screen.findByText("Введите название.")).toBeInTheDocument();
    expect(screen.getByText("Описание должно быть не длиннее 1 000 символов.")).toBeInTheDocument();
  });
});
