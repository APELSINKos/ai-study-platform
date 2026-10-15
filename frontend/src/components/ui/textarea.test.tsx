import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef } from "react";
import { describe, expect, it } from "vitest";

import { Field } from "./field";
import { Textarea } from "./textarea";

describe("Textarea", () => {
  it("is a multi-line text box that keeps line breaks", async () => {
    render(<Textarea aria-label="Description" />);

    const textarea = screen.getByRole("textbox", { name: "Description" });
    await userEvent.type(textarea, "First line{Enter}Second line");

    expect(textarea).toHaveValue("First line\nSecond line");
  });

  it("is focused by clicking its Field label", async () => {
    render(
      <Field label="Description">
        <Textarea />
      </Field>,
    );

    await userEvent.click(screen.getByText("Description"));

    expect(screen.getByRole("textbox", { name: "Description" })).toHaveFocus();
  });

  it("is linked to the Field error and hint", () => {
    render(
      <Field label="Description" hint="Optional." error="Keep it under 1000 characters.">
        <Textarea />
      </Field>,
    );

    const textarea = screen.getByRole("textbox", { name: "Description" });
    expect(textarea).toHaveAttribute("aria-invalid", "true");
    expect(textarea).toHaveAccessibleDescription("Keep it under 1000 characters. Optional.");
  });

  it("hands its element to a ref, as form libraries expect", () => {
    const ref = createRef<HTMLTextAreaElement>();

    render(<Textarea ref={ref} defaultValue="Chapter 3" />);

    expect(ref.current).toBeInstanceOf(HTMLTextAreaElement);
    expect(ref.current?.value).toBe("Chapter 3");
  });
});
