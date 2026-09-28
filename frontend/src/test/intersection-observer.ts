import { vi } from "vitest";

/**
 * jsdom has no IntersectionObserver. This stand-in records what is observed and lets a test
 * decide when elements scroll into view; with `immediately` they count as visible at once.
 */
export function stubIntersectionObserver({ immediately = false } = {}) {
  const observers: FakeIntersectionObserver[] = [];

  class FakeIntersectionObserver implements IntersectionObserver {
    readonly root = null;
    readonly rootMargin = "";
    readonly scrollMargin = "";
    readonly thresholds = [];
    private readonly targets = new Set<Element>();

    constructor(private readonly callback: IntersectionObserverCallback) {
      observers.push(this);
    }

    observe(target: Element) {
      this.targets.add(target);
      if (immediately) {
        this.reveal();
      }
    }

    unobserve(target: Element) {
      this.targets.delete(target);
    }

    disconnect() {
      this.targets.clear();
    }

    takeRecords(): IntersectionObserverEntry[] {
      return [];
    }

    reveal() {
      const entries = [...this.targets].map(
        (target) => ({ isIntersecting: true, target }) as IntersectionObserverEntry,
      );
      if (entries.length > 0) {
        this.callback(entries, this);
      }
    }
  }

  vi.stubGlobal("IntersectionObserver", FakeIntersectionObserver);

  return {
    /** Reports every observed element as visible. */
    revealAll() {
      for (const observer of observers) {
        observer.reveal();
      }
    },
  };
}
