/**
 * The search an address asks for with `?q=`, without the spaces around it; null when it asks for
 * none. A parameter given twice arrives as a list and asks for none either.
 */
export function searchQueryFrom(value: string | string[] | undefined): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const query = value.trim();
  return query === "" ? null : query;
}
