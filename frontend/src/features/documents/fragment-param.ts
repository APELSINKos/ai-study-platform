// Plain digits only: no sign, point or exponent. No document has a million fragments, so six
// digits are enough.
const FRAGMENT_PATTERN = /^\d{1,6}$/;

/**
 * The fragment an address opens its document at with `?fragment=`, by its place in the document
 * from 0; null when it names none. Anything but plain digits names none, and so does a parameter
 * given twice, which arrives as a list.
 */
export function fragmentFrom(value: string | string[] | undefined): number | null {
  if (typeof value !== "string" || !FRAGMENT_PATTERN.test(value)) {
    return null;
  }
  return Number(value);
}
