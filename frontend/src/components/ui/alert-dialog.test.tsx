import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef, useState } from "react";
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

  it("wraps a word too long for a line in the title and the question", async () => {
    const user = userEvent.setup();
    renderDialog();

    const dialog = await openWithKeyboard(user);

    // jsdom lays nothing out, so the rule that lets such a word break is checked instead.
    expect(within(dialog).getByRole("heading", { name: "Delete this workspace?" })).toHaveClass(
      "break-words",
    );
    expect(within(dialog).getByText("Its documents are deleted with it.")).toHaveClass(
      "break-words",
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

/** A list heading and one row whose delete removes the row, trigger and all. */
function RowWithDelete({ onConfirm }: { onConfirm: () => Promise<unknown> }) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [isRowShown, setIsRowShown] = useState(true);

  async function deleteRow() {
    await onConfirm();
    setIsRowShown(false);
  }

  return (
    <>
      <h2 ref={headingRef} tabIndex={-1}>
        Documents
      </h2>
      {isRowShown ? (
        <AlertDialog
          trigger={<Button variant="ghost">Delete lecture.pdf</Button>}
          title="Delete this document?"
          description="It cannot be brought back."
          confirmLabel="Delete"
          onConfirm={deleteRow}
          errorMessage={() => FAILURE_MESSAGE}
          focusAfterConfirm={headingRef}
        />
      ) : null}
    </>
  );
}

describe("AlertDialog with a focus target after the action", () => {
  async function confirmWithKeyboard(user: User): Promise<void> {
    await user.tab();
    await user.keyboard("{Enter}");
    await screen.findByRole("alertdialog", { name: "Delete this document?" });
    await user.tab();
    await user.keyboard("{Enter}");
  }

  it("moves focus there once the action succeeds, though the trigger is gone with it", async () => {
    const user = userEvent.setup();
    renderWithIntl(<RowWithDelete onConfirm={async () => undefined} />);

    await confirmWithKeyboard(user);

    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Delete lecture.pdf" })).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("heading", { name: "Documents" })).toHaveFocus());
  });

  it("still returns focus to the trigger when the question is dismissed", async () => {
    const user = userEvent.setup();
    renderWithIntl(<RowWithDelete onConfirm={async () => undefined} />);
    await user.tab();
    await user.keyboard("{Enter}");
    await screen.findByRole("alertdialog");

    await user.keyboard("{Escape}");

    await expectClosedWithFocusOn(screen.getByRole("button", { name: "Delete lecture.pdf" }));
  });

  it("returns focus to the trigger when the question is dismissed after a failure", async () => {
    const user = userEvent.setup();
    renderWithIntl(<RowWithDelete onConfirm={() => Promise.reject(new Error("offline"))} />);
    await confirmWithKeyboard(user);
    expect(await screen.findByRole("alert")).toHaveTextContent(FAILURE_MESSAGE);

    await user.keyboard("{Escape}");

    await expectClosedWithFocusOn(screen.getByRole("button", { name: "Delete lecture.pdf" }));
  });
});
