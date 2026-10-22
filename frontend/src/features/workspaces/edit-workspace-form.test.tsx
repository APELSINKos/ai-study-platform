import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "@/lib/api/client";
import { ApiError, NETWORK_ERROR_CODE } from "@/lib/api/errors";
import type { Locale } from "@/i18n/config";
import { queryKeys } from "@/lib/query-keys";
import { renderWithIntl } from "@/test/render";

import { EditWorkspaceForm } from "./edit-workspace-form";
import { workspaceFixture } from "./test-fixtures";

vi.mock("@/lib/api/client", () => ({ apiFetch: vi.fn() }));

const apiFetchMock = vi.mocked(apiFetch);

const WORKSPACE = workspaceFixture(4, {
  name: "Statistics",
  description: "Hypothesis testing",
  exam_date: "2026-10-28",
});
const WORKSPACE_PATH = `/workspaces/${WORKSPACE.id}`;

function renderForm(locale: Locale = "en") {
  const onSaved = vi.fn();
  const onCancel = vi.fn();
  const view = renderWithIntl(
    <EditWorkspaceForm workspace={WORKSPACE} onSaved={onSaved} onCancel={onCancel} />,
    { locale },
  );
  return { ...view, onSaved, onCancel };
}

function save(): Promise<void> {
  return userEvent.click(screen.getByRole("button", { name: "Save changes" }));
}

async function replaceText(label: string, text: string): Promise<void> {
  const field = screen.getByLabelText(label);
  await userEvent.clear(field);
  if (text) {
    await userEvent.type(field, text);
  }
}

describe("EditWorkspaceForm", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it("opens filled in with the workspace and the cursor in its name", () => {
    renderForm();

    expect(screen.getByRole("form", { name: "Edit workspace" })).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveValue("Statistics");
    expect(screen.getByLabelText("Name")).toHaveFocus();
    expect(screen.getByLabelText("Description")).toHaveValue("Hypothesis testing");
    expect(screen.getByLabelText("Exam date")).toHaveValue("2026-10-28");
  });

  it("saves with a secondary button and cancels with a ghost one", () => {
    renderForm();

    expect(screen.getByRole("button", { name: "Save changes" })).toHaveAttribute(
      "data-variant",
      "secondary",
    );
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveAttribute("data-variant", "ghost");
    expect(document.querySelector('[data-variant="primary"]')).toBeNull();
  });

  it("sends only what changed and reports once it is saved", async () => {
    apiFetchMock.mockResolvedValue({ ...WORKSPACE, name: "Applied statistics" });
    const { onSaved } = renderForm();

    await replaceText("Name", "  Applied statistics ");
    await save();

    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(apiFetchMock).toHaveBeenCalledTimes(1);
    expect(apiFetchMock).toHaveBeenCalledWith(WORKSPACE_PATH, {
      method: "PATCH",
      json: { name: "Applied statistics" },
    });
  });

  it("removes a description and an exam date that were cleared", async () => {
    apiFetchMock.mockResolvedValue({ ...WORKSPACE, description: null, exam_date: null });
    const { onSaved } = renderForm();

    await replaceText("Description", "");
    fireEvent.change(screen.getByLabelText("Exam date"), { target: { value: "" } });
    await save();

    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(apiFetchMock).toHaveBeenCalledWith(WORKSPACE_PATH, {
      method: "PATCH",
      json: { description: null, exam_date: null },
    });
  });

  it("closes without a request when nothing changed", async () => {
    const { onSaved } = renderForm();

    await save();

    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("shows the saved workspace at once and refreshes every workspace view", async () => {
    const saved = { ...WORKSPACE, name: "Applied statistics" };
    apiFetchMock.mockResolvedValue(saved);
    const { onSaved, queryClient } = renderForm();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    await replaceText("Name", "Applied statistics");
    await save();

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(queryClient.getQueryData(queryKeys.workspace(WORKSPACE.id))).toEqual(saved);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["workspaces"] });
  });

  it("asks for a name before sending anything", async () => {
    const { onSaved } = renderForm();

    await replaceText("Name", "   ");
    await save();

    expect(await screen.findByText("Enter a name.")).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveFocus();
    expect(apiFetchMock).not.toHaveBeenCalled();
    expect(onSaved).not.toHaveBeenCalled();
  });

  it("points at a field the server rejected, in its own words", async () => {
    apiFetchMock.mockRejectedValue(
      new ApiError({
        status: 422,
        code: "validation_error",
        message: "The request contains invalid data.",
        details: [{ field: "name", message: "String should have at most 120 characters" }],
      }),
    );
    const { onSaved } = renderForm();

    await replaceText("Name", "Applied statistics");
    await save();

    expect(await screen.findByText("Check this field.")).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveAttribute("aria-invalid", "true");
    expect(screen.queryByText(/120 characters|invalid data/)).not.toBeInTheDocument();
    expect(onSaved).not.toHaveBeenCalled();
  });

  it.each([
    [
      new ApiError({ status: 0, code: NETWORK_ERROR_CODE, message: "x" }),
      "The API could not be reached. Check your connection and try again.",
    ],
    [
      new ApiError({ status: 404, code: "workspace_not_found", message: "x" }),
      "This workspace no longer exists.",
    ],
    [
      new ApiError({ status: 500, code: "internal_error", message: "Internal server error." }),
      "Your changes could not be saved. Try again.",
    ],
  ])("explains a failure to save (%o)", async (error, expected) => {
    apiFetchMock.mockRejectedValue(error);
    const { onSaved } = renderForm();

    await replaceText("Name", "Applied statistics");
    await save();

    expect(await screen.findByText(expected)).toHaveAttribute("role", "alert");
    expect(screen.queryByText("Internal server error.")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save changes" })).not.toHaveAttribute("aria-busy");
    expect(onSaved).not.toHaveBeenCalled();
  });

  it("sends one request however often it is submitted", async () => {
    // Answered only when the test says so, so every click lands while the request is pending.
    const saving = Promise.withResolvers<typeof WORKSPACE>();
    apiFetchMock.mockReturnValue(saving.promise);
    const { onSaved } = renderForm();
    await replaceText("Name", "Applied statistics");
    const button = screen.getByRole("button", { name: "Save changes" });

    await userEvent.click(button);
    await userEvent.click(button);
    fireEvent.submit(button.closest("form") as HTMLFormElement);
    saving.resolve(WORKSPACE);
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));

    expect(apiFetchMock).toHaveBeenCalledTimes(1);
  });

  it("goes back without a request on Cancel", async () => {
    const { onCancel } = renderForm();

    await replaceText("Name", "Applied statistics");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("speaks Russian", async () => {
    renderForm("ru");

    expect(screen.getByRole("form", { name: "Изменить пространство" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Отмена" })).toBeInTheDocument();

    await replaceText("Название", "");
    await userEvent.click(screen.getByRole("button", { name: "Сохранить изменения" }));

    expect(await screen.findByText("Введите название.")).toBeInTheDocument();
  });
});
