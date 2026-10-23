import { useTranslations } from "next-intl";

import { ComingNext } from "../coming-next";
import { LazyMount } from "../lazy-mount";
import { FlashcardDemo } from "./flashcard-demo";

/** Room the demo takes once mounted (deck, rating row and status line), reserved up front. */
const DEMO_BOX = "h-[27.5rem] sm:h-[29.5rem]";

export function Practice() {
  const t = useTranslations("Landing.practice");

  return (
    <section aria-labelledby="practice-title" className="notebook-row mt-32 sm:mt-44">
      <div className="grid gap-12 lg:grid-cols-[minmax(0,6fr)_minmax(0,5fr)] lg:items-center lg:gap-16">
        {/* Text comes first when read; on wide screens the demo sits on the left, by the margin. */}
        <div className="lg:order-2">
          <h2 id="practice-title" className="font-display text-headline font-semibold text-balance">
            {t("title")}
          </h2>
          <ComingNext className="mt-3" />
          <p className="text-ink-soft mt-4 max-w-[46ch] text-lg leading-8">{t("body")}</p>
        </div>
        <div className="relative max-w-md lg:order-1">
          {/* From tablet width up the note hangs in the notebook margin beside the deck. */}
          <p className="margin-note mb-5 md:absolute md:top-3 md:right-[calc(100%+var(--margin-gap))] md:mb-0 md:w-[calc(var(--margin-column)-1.25rem)] md:text-right">
            {t("note")}
          </p>
          <LazyMount className={DEMO_BOX}>
            <FlashcardDemo />
          </LazyMount>
        </div>
      </div>
    </section>
  );
}
