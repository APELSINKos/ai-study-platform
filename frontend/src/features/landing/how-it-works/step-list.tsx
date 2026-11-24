import { useTranslations } from "next-intl";

import { STEPS, type Step } from "./timeline";

/**
 * The four numbered steps beside the map. The current one gets its number circled in pen. Where
 * the list would not fit on screen next to the map, the steps share one spot and only the current
 * one is visible (all four stay in the reading order); without motion they are simply listed.
 */
export function StepList({ active }: { active: Step }) {
  const t = useTranslations("Landing.how.steps");

  return (
    <ol className="grid gap-y-9">
      {STEPS.map((step, index) => {
        const isActive = step === active;
        return (
          <li
            key={step}
            aria-current={isActive ? "step" : undefined}
            data-active={isActive}
            className="cramped:motion-safe:data-[active=false]:opacity-0 cramped:motion-safe:[grid-area:1/1] relative transition-opacity duration-300"
          >
            <h3 className="font-display flex items-center gap-3 text-xl leading-snug font-semibold">
              <StepNumber number={index + 1} isActive={isActive} />
              {t(`${step}.title`)}
            </h3>
            <p className="text-ink-soft mt-2 max-w-[48ch] leading-7">{t(`${step}.body`)}</p>
          </li>
        );
      })}
    </ol>
  );
}

/** A loop that overshoots its start a little, the way a pen circles something on paper. */
const PEN_CIRCLE = "M31 5C24 2 12 3 6 9 1 15 3 25 10 30c7 5 20 4 27-1 6-5 6-14 1-20-4-4-10-6-17-5";

function StepNumber({ number, isActive }: { number: number; isActive: boolean }) {
  return (
    // From tablet width up the number hangs in the notebook margin, next to the red rule.
    <span className="text-pen relative inline-grid size-9 flex-none place-items-center text-lg font-normal italic md:absolute md:top-[-0.1rem] md:right-[calc(100%+var(--margin-gap))]">
      {number}
      {/* 48 by 40 px around the 36px number, the same proportions as the drawing. */}
      <svg
        aria-hidden
        viewBox="0 0 44 36"
        className="absolute -top-0.5 -left-1.5 h-10 w-12 overflow-visible motion-reduce:hidden"
      >
        <path
          d={PEN_CIRCLE}
          pathLength={1}
          fill="none"
          strokeWidth={1.5}
          strokeLinecap="round"
          className="stroke-pen [stroke-dasharray:1] [transition:stroke-dashoffset_500ms_var(--ease-out-soft),opacity_150ms_linear]"
          // Hidden as well as undrawn: a round cap would otherwise leave a dot behind.
          style={{ strokeDashoffset: isActive ? 0 : 1, opacity: isActive ? 1 : 0 }}
        />
      </svg>
    </span>
  );
}
