import type { MetaOut } from "@/lib/api/types";

/** The limits GET /meta states, which a file must meet before it is sent. */
export type FileRules = Pick<MetaOut, "allowed_extensions" | "max_upload_bytes">;

/** Why a file is turned down before it is sent. */
export type FileRejection = "type" | "tooLarge" | "empty";

/**
 * The extension of a file name in lower case with its dot, or "" when it has none. Trailing
 * spaces are dropped first, as the API drops them from the names it stores.
 */
export function extensionOf(name: string): string {
  const trimmed = name.trim();
  const dot = trimmed.lastIndexOf(".");
  if (dot === -1 || dot === trimmed.length - 1) {
    return "";
  }
  return trimmed.slice(dot).toLowerCase();
}

/** The first rule a file breaks, or null when it can be sent. */
export function checkFile(
  file: Pick<File, "name" | "size">,
  rules: FileRules,
): FileRejection | null {
  if (!rules.allowed_extensions.includes(extensionOf(file.name))) {
    return "type";
  }
  if (file.size === 0) {
    return "empty";
  }
  if (file.size > rules.max_upload_bytes) {
    return "tooLarge";
  }
  return null;
}

/** The file picker's `accept` value: the allowed extensions. */
export function acceptAttribute(rules: FileRules): string {
  return rules.allowed_extensions.join(",");
}

/** The allowed extensions as a list for a sentence, such as ".pdf, .md, and .txt". */
export function listExtensions(rules: FileRules, locale: string): string {
  return new Intl.ListFormat(locale, { type: "conjunction" }).format(rules.allowed_extensions);
}
