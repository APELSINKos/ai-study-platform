import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Locale } from "@/i18n/config";
import { ApiError } from "@/lib/api/errors";
import { renderWithIntl } from "@/test/render";

import { AlertDialog } from "./alert-dialog";
import { Button } from "./button";

type User = ReturnType<typeof userEvent.setup>;

const FAILURE_MESSAGE = "The workspace could not be deleted.";

interface DialogOptions {
  onConfirm?: () => Promise<unknown>;
  locale?: Locale;
}

function renderDialog({ onConfirm = async () => undefined, locale = "en" }: DialogOptions = {}) {
  const errorMessage = vi.fn<(error: unknown) => string>(() => FAILURE_MESSAGE);
  renderWithIntl(
    <AlertDialog
      trigger={<Button variant="danger">Delete workspace</Button>}
      title="Delete this workspace?"
      description="Its documents are deleted with it."
      confirmLabel="Delete"
      onConfirm={onConfirm}
      errorMessage={errorMessage}
    />,
    { locale },
  );
  return { errorMessage, trigger: screen.getByRole("button", { name: "Delete workspace" }) };
}

async function openWithKeyboard(user: User): Promise<HTMLElement> {
  await user.tab();
  await user.keyboard("{Enter}");
  return screen.findByRole("alertdialog", { name: "Delete this workspace?" });
}

async function expectClosedWithFocusOn(trigger: HTMLElement): Promise<void> {
  await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  await waitFor(() => expect(trigger).toHaveFocus());
}

describe("AlertDialog", () => {
  it("opens from the keyboard with the safe choice focused", async () => {
    const user = userEvent.setup();
    renderDialog();

    const dialog = await openWithKeyboard(user);

    expect(dialog).toHaveAccessibleDescription("Its documents are deleted with it.");
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    expect(screen.getByRole("button", { name: "Delete" })).toHaveAttribute(
      "data-variant",
      "danger",
    );
  });

  it("closes on Escape and returns focus to the trigger", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn(async () => undefined);
    const { trigger } = renderDialog({ onConfirm });
    await openWithKeyboard(user);

    await user.keyboard("{Escape}");

    await expectClosedWithFocusOn(trigger);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("closes from Cancel and returns focus to the trigger", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn(async () => undefined);
    const { trigger } = renderDialog({ onConfirm });
    await openWithKeyboard(user);

    await user.keyboard("{Enter}");

    await expectClosedWithFocusOn(trigger);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("stays open while the action runs and closes once it succeeds", async () => {
    const user = userEvent.setup();
    const action = Promise.withResolvers<void>();
    const onConfirm = vi.fn(() => action.promise);
    const { trigger } = renderDialog({ onConfirm });
    await openWithKeyboard(user);

    await user.tab();
    const confirm = screen.getByRole("button", { name: "Delete" });
    expect(confirm).toHaveFocus();
    await user.keyboard("{Enter}");

    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(confirm).toHaveAttribute("aria-busy", "true");
    await user.keyboard("{Enter}");
    await user.keyboard("{Escape}");
    await user.tab({ shift: true });
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(onConfirm).toHaveBeenCalledTimes(1);

    action.resolve();

    await expectClosedWithFocusOn(trigger);
  });

  it("shows the translated error inside on failure and lets the user try again", async () => {
    const user = userEvent.setup();
    const failure = new ApiError({ status: 500, code: "http_error", message: "Server error." });
    const onConfirm = vi
      .fn<() => Promise<void>>()
      .mockRejectedValueOnce(failure)
      .mockResolvedValueOnce(undefined);
    const { errorMessage, trigger } = renderDialog({ onConfirm });
    await openWithKeyboard(user);
    await user.tab();
    await user.keyboard("{Enter}");

    expect(await screen.findByRole("alert")).toHaveTextContent(FAILURE_MESSAGE);
    expect(errorMessage).toHaveBeenCalledWith(failure);
    expect(screen.queryByText("Server error.")).not.toBeInTheDocument();
    const confirm = screen.getByRole("button", { name: "Delete" });
    expect(confirm).not.toHaveAttribute("aria-busy");
    expect(confirm).toHaveFocus();

    await user.keyboard("{Enter}");

    await expectClosedWithFocusOn(trigger);
    expect(onConfirm).toHaveBeenCalledTimes(2);
  });

  it("can be dismissed after a failure and forgets the error when opened again", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn<() => Promise<void>>().mockRejectedValue(new Error("offline"));
    const { trigger } = renderDialog({ onConfirm });
    await openWithKeyboard(user);
    await user.tab();
    await user.keyboard("{Enter}");
    await screen.findByRole("alert");

    await user.keyboard("{Escape}");
    await expectClosedWithFocusOn(trigger);
    await user.keyboard("{Enter}");

    expect(
      await screen.findByRole("alertdialog", { name: "Delete this workspace?" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("speaks Russian", async () => {
    const user = userEvent.setup();
    renderDialog({ locale: "ru" });

    await openWithKeyboard(user);

    expect(screen.getByRole("button", { name: "Отмена" })).toHaveFocus();
  });
});
