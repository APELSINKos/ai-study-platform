import { useCallback, useEffect, useRef, type RefObject } from "react";

/** Whether the focus has dropped to the page, as it does when the focused element is removed. */
function isFocusLost(): boolean {
  return document.activeElement === null || document.activeElement === document.body;
}

/**
 * Keeps the keyboard focus in place when new content replaces the control that asked for it,
 * such as Try again: the control has the focus as it goes, and the focus would drop to the top
 * of the page. Call the returned function as the control is used; the next time `view` changes,
 * `target` takes the focus, unless the user has moved it elsewhere meanwhile.
 */
export function useFocusOnArrival(
  view: string | boolean,
  target: RefObject<HTMLElement | null>,
): () => void {
  const pendingRef = useRef(false);

  useEffect(() => {
    if (!pendingRef.current) {
      return;
    }
    pendingRef.current = false;
    if (isFocusLost()) {
      target.current?.focus();
    }
  }, [view, target]);

  return useCallback(() => {
    pendingRef.current = true;
  }, []);
}
