const CONTROL_CHARACTER_PATTERN = /[\u0000-\u001f\u007f]/;
// Origin a real request never has, used only so `new URL` can resolve a path in isolation.
const DUMMY_ORIGIN = "https://recall.invalid";

/**
 * Guards the `?next=` redirect target against open redirects. Only a same-origin
 * absolute path is allowed. The value is resolved against a fixed dummy origin the
 * way a browser resolves an href, which collapses dot segments (`.`, `..`, and their
 * percent-encoded forms) the same way a browser would before ever navigating: if that
 * changes the origin, or the resolved path starts with `//` or `/\` (both parsed as a
 * scheme-relative URL), the value is rejected.
 */
export function safeNext(value: string | null | undefined): string | null {
  if (!value || !value.startsWith("/") || CONTROL_CHARACTER_PATTERN.test(value)) {
    return null;
  }
  let url: URL;
  try {
    url = new URL(value, DUMMY_ORIGIN);
  } catch {
    return null;
  }
  if (url.origin !== DUMMY_ORIGIN) {
    return null;
  }
  if (url.pathname.startsWith("//") || url.pathname.startsWith("/\\")) {
    return null;
  }
  return `${url.pathname}${url.search}${url.hash}`;
}
