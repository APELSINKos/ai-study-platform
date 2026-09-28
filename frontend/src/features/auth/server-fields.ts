import type { ApiErrorDetail } from "@/lib/api/errors";

export interface MatchedServerFields<Field extends string> {
  fields: Field[];
  hasUnmatched: boolean;
}

/** Maps the fields named in `validation_error` details onto form fields. */
export function matchServerFields<Field extends string>(
  details: readonly ApiErrorDetail[],
  fieldByServerName: Readonly<Record<string, Field>>,
): MatchedServerFields<Field> {
  const fields: Field[] = [];
  let hasUnmatched = false;
  for (const { field } of details) {
    const formField =
      field && Object.hasOwn(fieldByServerName, field) ? fieldByServerName[field] : undefined;
    if (formField === undefined) {
      hasUnmatched = true;
    } else if (!fields.includes(formField)) {
      fields.push(formField);
    }
  }
  return { fields, hasUnmatched };
}
