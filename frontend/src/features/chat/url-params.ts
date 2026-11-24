const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type SessionParam = { kind: "none" } | { kind: "invalid" } | { kind: "valid"; id: string };

/**
 * Parses `?session=` from the address bar. Absent or empty opens the session index; a malformed or
 * duplicated value is marked invalid so the UI shows "not found" without firing a 422 request.
 */
export function sessionParamFrom(value: string | string[] | undefined): SessionParam {
  if (value === undefined || value === "") {
    return { kind: "none" };
  }
  if (typeof value !== "string" || !UUID_PATTERN.test(value)) {
    return { kind: "invalid" };
  }
  return { kind: "valid", id: value.toLowerCase() };
}

/** Parses `?workspace=` from the address bar, returning a lowercase UUID or null. */
export function workspaceParamFrom(value: string | string[] | undefined): string | null {
  if (typeof value !== "string" || !UUID_PATTERN.test(value)) {
    return null;
  }
  return value.toLowerCase();
}
