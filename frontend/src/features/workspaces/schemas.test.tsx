import { screen } from "@testing-library/react";
import { useTranslations } from "next-intl";
import { describe, expect, it } from "vitest";

import { renderWithIntl } from "@/test/render";

import { toCreateRequest, workspaceFormSchema, type WorkspaceFormValues } from "./schemas";

const VALID: WorkspaceFormValues = { name: "Organic chemistry", description: "", examDate: "" };

function Probe({ values }: { values: WorkspaceFormValues }) {
  const t = useTranslations("Workspaces.validation");
  const result = workspaceFormSchema(t).safeParse(values);
  const lines = result.success
    ? ["valid"]
    : result.error.issues.map((issue) => `${issue.path.join(".")}: ${issue.message}`);
  return (
    <ul>
      {lines.map((line) => (
        <li key={line}>{line}</li>
      ))}
    </ul>
  );
}

function verdict(values: Partial<WorkspaceFormValues>): string[] {
  renderWithIntl(<Probe values={{ ...VALID, ...values }} />);
  return screen.getAllByRole("listitem").map((item) => item.textContent ?? "");
}

describe("workspaceFormSchema", () => {
  it("accepts a name alone", () => {
    expect(verdict({})).toEqual(["valid"]);
  });

  it("rejects the NUL character the database cannot store", () => {
    expect(verdict({ name: "Organic\u0000chemistry", description: "Week\u00001" })).toEqual([
      "name: This text contains a character that cannot be saved.",
      "description: This text contains a character that cannot be saved.",
    ]);
  });

  it.each([["2026-02-30"], ["2026-13-01"], ["28.10.2026"]])(
    "rejects the exam date %j, which is no calendar day",
    (examDate) => {
      expect(verdict({ examDate })).toEqual(["examDate: Enter a valid date."]);
    },
  );

  it("accepts a real exam date", () => {
    expect(verdict({ examDate: "2028-02-29" })).toEqual(["valid"]);
  });
});

describe("toCreateRequest", () => {
  it("trims the text and sends what is left empty as null", () => {
    expect(
      toCreateRequest({ name: "  Organic chemistry ", description: "   ", examDate: "" }),
    ).toEqual({ name: "Organic chemistry", description: null, exam_date: null });
  });

  it("keeps a description and an exam date", () => {
    expect(
      toCreateRequest({ name: "Statistics", description: " Week 1 ", examDate: "2026-10-28" }),
    ).toEqual({ name: "Statistics", description: "Week 1", exam_date: "2026-10-28" });
  });
});
