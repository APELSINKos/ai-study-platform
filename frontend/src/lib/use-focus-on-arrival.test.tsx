import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef } from "react";
import { describe, expect, it } from "vitest";

import { useFocusOnArrival } from "./use-focus-on-arrival";

/** Try again in place of content that a later render brings, with a field elsewhere. */
function Section({ view, offersRetry }: { view: string; offersRetry: boolean }) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  const focusHeadingOnArrival = useFocusOnArrival(view, headingRef);
  return (
    <>
      <h2 ref={headingRef} tabIndex={-1}>
        Fragments
      </h2>
      {offersRetry ? <button onClick={focusHeadingOnArrival}>Try again</button> : null}
      <input aria-label="Notes" />
    </>
  );
}

function heading(): HTMLElement {
  return screen.getByRole("heading", { name: "Fragments" });
}

describe("useFocusOnArrival", () => {
  it("gives the focus to the target when the content replaces the control that asked for it", async () => {
    const { rerender } = render(<Section view="failed" offersRetry />);

    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    rerender(<Section view="loaded" offersRetry={false} />);

    expect(heading()).toHaveFocus();
  });

  it("waits for the view to change, however often the page renders before", async () => {
    const { rerender } = render(<Section view="failed" offersRetry />);

    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    rerender(<Section view="failed" offersRetry />);
    expect(heading()).not.toHaveFocus();

    rerender(<Section view="loaded" offersRetry={false} />);
    expect(heading()).toHaveFocus();
  });

  it("leaves the focus where the user has moved it meanwhile", async () => {
    const { rerender } = render(<Section view="failed" offersRetry />);

    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await userEvent.click(screen.getByLabelText("Notes"));
    rerender(<Section view="loaded" offersRetry={false} />);

    expect(screen.getByLabelText("Notes")).toHaveFocus();
  });

  it("moves nothing when the content changes without being asked for", () => {
    const { rerender } = render(<Section view="failed" offersRetry />);

    rerender(<Section view="loaded" offersRetry={false} />);

    expect(heading()).not.toHaveFocus();
  });

  it("moves the focus once, not again when the view changes later", async () => {
    const { rerender } = render(<Section view="failed" offersRetry />);
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    rerender(<Section view="loaded" offersRetry={false} />);
    heading().blur();

    rerender(<Section view="failed" offersRetry />);

    expect(heading()).not.toHaveFocus();
  });
});
