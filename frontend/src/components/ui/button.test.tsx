import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Button } from "./button";

describe("Button", () => {
  it("is a secondary, non-submitting button unless told otherwise", () => {
    render(<Button>Save draft</Button>);

    const button = screen.getByRole("button", { name: "Save draft" });
    expect(button).toHaveAttribute("data-variant", "secondary");
    expect(button).toHaveAttribute("type", "button");
  });

  it("renders the primary action", () => {
    render(<Button variant="primary">Upload</Button>);

    expect(screen.getByRole("button", { name: "Upload" })).toHaveAttribute(
      "data-variant",
      "primary",
    );
  });

  it("keeps an explicit submit type", () => {
    render(<Button type="submit">Sign in</Button>);

    expect(screen.getByRole("button", { name: "Sign in" })).toHaveAttribute("type", "submit");
  });

  it("blocks clicks and announces progress while loading", async () => {
    const onClick = vi.fn();
    render(
      <Button isLoading onClick={onClick}>
        Generate quiz
      </Button>,
    );

    const button = screen.getByRole("button", { name: "Generate quiz" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    await userEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("styles a link when rendered as its child", () => {
    render(
      <Button asChild variant="primary">
        <a href="/register">Create account</a>
      </Button>,
    );

    const link = screen.getByRole("link", { name: "Create account" });
    expect(link).toHaveAttribute("href", "/register");
    expect(link).toHaveAttribute("data-variant", "primary");
    expect(link).not.toHaveAttribute("type");
  });
});
