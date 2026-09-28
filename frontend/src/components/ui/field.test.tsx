import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { Field } from "./field";
import { Input } from "./input";

describe("Field", () => {
  it("clicking the label focuses the input", async () => {
    render(
      <Field label="Email">
        <Input type="email" />
      </Field>,
    );

    await userEvent.click(screen.getByText("Email"));

    expect(screen.getByRole("textbox")).toHaveFocus();
  });

  it("links the hint to the input", () => {
    render(
      <Field label="Email" hint="We will not share it.">
        <Input type="email" />
      </Field>,
    );

    const input = screen.getByRole("textbox");
    const hint = screen.getByText("We will not share it.");
    expect(input).toHaveAttribute("aria-describedby", hint.id);
    expect(input).not.toHaveAttribute("aria-invalid");
  });

  it("announces and links the error", () => {
    render(
      <Field label="Email" error="Enter a valid email.">
        <Input type="email" />
      </Field>,
    );

    const input = screen.getByRole("textbox");
    const error = screen.getByRole("alert");
    expect(error).toHaveTextContent("Enter a valid email.");
    expect(input).toHaveAttribute("aria-describedby", error.id);
    expect(input).toHaveAttribute("aria-invalid", "true");
  });

  it("has no alert role when there is no error", () => {
    render(
      <Field label="Email">
        <Input type="email" />
      </Field>,
    );

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("links both the hint and the error when both are present", () => {
    render(
      <Field label="Email" hint="We will not share it." error="Enter a valid email.">
        <Input type="email" />
      </Field>,
    );

    const input = screen.getByRole("textbox");
    const error = screen.getByRole("alert");
    const hint = screen.getByText("We will not share it.");
    expect(input.getAttribute("aria-describedby")).toBe(`${error.id} ${hint.id}`);
  });
});
