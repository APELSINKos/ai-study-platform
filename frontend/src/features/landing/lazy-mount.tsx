"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

/** Start mounting one screen before the section scrolls in, so it is ready when it arrives. */
const PRELOAD_MARGIN = "100% 0px";

/**
 * Renders its children only once they come near the viewport. The wrapper keeps its size from
 * `className` the whole time, so mounting never shifts the page.
 */
export function LazyMount({ className, children }: { className?: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [isNear, setIsNear] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node) {
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setIsNear(true);
          observer.disconnect();
        }
      },
      { rootMargin: PRELOAD_MARGIN },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <div ref={ref} className={className}>
      {isNear ? children : null}
    </div>
  );
}
