import { vi, type Mock } from "vitest";

/**
 * jsdom lays nothing out, so it has no scrollIntoView. This stand-in records each call; the
 * element a call scrolled to is in `mock.contexts`.
 */
export function stubScrollIntoView(): Mock<Element["scrollIntoView"]> {
  const scrollIntoView = vi.fn<Element["scrollIntoView"]>();
  Object.defineProperty(Element.prototype, "scrollIntoView", {
    configurable: true,
    writable: true,
    value: scrollIntoView,
  });
  return scrollIntoView;
}
