const CONTROL_CHARACTER_PATTERN = /[\u0000-\u001f\u007f]/;

/**
 * Guards the `?next=` redirect target against open redirects. Only a same-origin
 * absolute path is allowed: it must start with a single `/`, never `//` or `/\`
 * (both are parsed as a scheme-relative URL by browsers), and carry no control
 * characters. Percent-decoding is the caller's responsibility.
 */
export function safeNext(value: string | null | undefined): string | null {
  if (!value || !value.startsWith("/")) {
    return null;
  }
  const second = value[1];
  if (second === "/" || second === "\\") {
    return null;
  }
  if (CONTROL_CHARACTER_PATTERN.test(value)) {
    return null;
  }
  return value;
}
