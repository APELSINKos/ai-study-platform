import { screen } from "@testing-library/react";
import { useTranslations } from "next-intl";
import { describe, expect, it } from "vitest";

import { renderWithIntl } from "@/test/render";

import {
  toCreateRequest,
  toFormValues,
  toUpdateRequest,
  workspaceFormSchema,
  type WorkspaceFormValues,
} from "./schemas";
import { workspaceFixture } from "./test-fixtures";

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

describe("toFormValues", () => {
  it("fills the form with the workspace, leaving out what it does not have", () => {
    expect(toFormValues(workspaceFixture(1, { name: "Statistics" }))).toEqual({
      name: "Statistics",
      description: "",
      examDate: "",
    });
    expect(
      toFormValues(
        workspaceFixture(1, { description: "Chapters 1 to 6", exam_date: "2026-10-28" }),
      ),
    ).toEqual({ name: "Workspace 1", description: "Chapters 1 to 6", examDate: "2026-10-28" });
  });
});

describe("toUpdateRequest", () => {
  const OPENED: WorkspaceFormValues = {
    name: "Statistics",
    description: "Hypothesis testing",
    examDate: "2026-10-28",
  };

  it("sends only the fields that changed since the form opened", () => {
    expect(toUpdateRequest({ ...OPENED, name: " Applied statistics " }, OPENED)).toEqual({
      name: "Applied statistics",
    });
    expect(toUpdateRequest({ ...OPENED, examDate: "2026-11-02" }, OPENED)).toEqual({
      exam_date: "2026-11-02",
    });
  });

  it("clears an emptied description or exam date with null", () => {
    expect(toUpdateRequest({ ...OPENED, description: "  ", examDate: "" }, OPENED)).toEqual({
      description: null,
      exam_date: null,
    });
  });

  it("finds nothing to send when only surrounding spaces were added", () => {
    expect(
      toUpdateRequest(
        { ...OPENED, name: "Statistics  ", description: " Hypothesis testing" },
        OPENED,
      ),
    ).toBeNull();
  });
});
