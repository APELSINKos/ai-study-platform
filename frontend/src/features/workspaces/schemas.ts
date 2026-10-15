import type { useTranslations } from "next-intl";
import { z } from "zod";

import type { WorkspaceCreateRequest } from "@/lib/api/types";

import { parseExamDate } from "./exam-countdown";

// Mirrors the limits in backend/app/schemas/workspaces.py.
export const WORKSPACE_NAME_MAX_LENGTH = 120;
export const WORKSPACE_DESCRIPTION_MAX_LENGTH = 1000;
// PostgreSQL text cannot hold NUL, so the backend rejects it.
const NUL = "\u0000";

type WorkspaceValidationTranslator = ReturnType<typeof useTranslations<"Workspaces.validation">>;

export interface WorkspaceFormValues {
  name: string;
  description: string;
  /** The date input's value: `YYYY-MM-DD`, or empty for no exam. */
  examDate: string;
}

/** Python measures text in code points, so an emoji counts once here as well. */
function characterCount(value: string): number {
  return Array.from(value).length;
}

function storable(value: string): boolean {
  return !value.includes(NUL);
}

export function workspaceFormSchema(t: WorkspaceValidationTranslator) {
  return z.object({
    name: z
      .string()
      .trim()
      .min(1, t("nameRequired"))
      .refine(
        (value) => characterCount(value) <= WORKSPACE_NAME_MAX_LENGTH,
        t("nameTooLong", { max: WORKSPACE_NAME_MAX_LENGTH }),
      )
      .refine(storable, t("unsupportedCharacter")),
    description: z
      .string()
      .trim()
      .refine(
        (value) => characterCount(value) <= WORKSPACE_DESCRIPTION_MAX_LENGTH,
        t("descriptionTooLong", { max: WORKSPACE_DESCRIPTION_MAX_LENGTH }),
      )
      .refine(storable, t("unsupportedCharacter")),
    examDate: z
      .string()
      .refine((value) => value === "" || parseExamDate(value) !== null, t("examDateInvalid")),
  });
}

/** A blank description and an empty date are sent as null: the workspace has neither. */
export function toCreateRequest(values: WorkspaceFormValues): WorkspaceCreateRequest {
  return {
    name: values.name.trim(),
    description: values.description.trim() || null,
    exam_date: values.examDate || null,
  };
}
