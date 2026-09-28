import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { IndexCard, IndexCardBody, IndexCardHeader } from "./index-card";

describe("IndexCard", () => {
  it("renders children and forwards className and other props", () => {
    render(
      <IndexCard className="max-w-md" data-testid="card">
        content
      </IndexCard>,
    );

    const card = screen.getByTestId("card");
    expect(card).toHaveClass("index-card", "max-w-md");
    expect(card).toHaveTextContent("content");
  });
});

describe("IndexCardHeader", () => {
  it("is the element carrying the red rule, and forwards className and other props", () => {
    render(
      <IndexCardHeader className="extra" data-testid="header">
        <h1>Title</h1>
      </IndexCardHeader>,
    );

    const header = screen.getByTestId("header");
    expect(header).toHaveClass("index-card-header", "extra");
    expect(screen.getByRole("heading", { name: "Title" })).toBeInTheDocument();
  });
});

describe("IndexCardBody", () => {
  it("forwards className and other props", () => {
    render(
      <IndexCardBody className="extra" data-testid="body">
        body content
      </IndexCardBody>,
    );

    const body = screen.getByTestId("body");
    expect(body).toHaveClass("extra");
    expect(body).toHaveTextContent("body content");
  });
});
