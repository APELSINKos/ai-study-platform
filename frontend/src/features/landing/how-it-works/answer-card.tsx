import { useTranslations } from "next-intl";
import { Fragment, type CSSProperties } from "react";

import { cn } from "@/lib/utils";

import styles from "./answer-card.module.css";
import { CitationMark } from "./citation-mark";
import { tokenizeAnswer } from "./tokenize-answer";

/**
 * The question and the answer Recall writes for it, as an index card under the map. The card
 * appears with the question and the answer types itself out once `isTyped` turns on.
 */
export function AnswerCard({
  isShown,
  isTyped,
  className,
}: {
  isShown: boolean;
  isTyped: boolean;
  className?: string;
}) {
  const t = useTranslations("Landing.how");
  const tokens = tokenizeAnswer(t("answer"));
  const cardStyle = { "--count": tokens.length } as CSSProperties;

  return (
    <div
      data-testid="answer-card"
      data-shown={isShown}
      data-typed={isTyped}
      style={cardStyle}
      className={cn("index-card", styles.card, className)}
    >
      <p className="index-card-header flex items-start gap-3 px-4 py-3 text-sm font-medium sm:px-5">
        <QuestionDot />
        {t("question")}
      </p>
      <div className="px-4 pt-3 pb-4 sm:px-5">
        <p className="font-display text-[0.9375rem] leading-7 sm:text-base">
          {tokens.map((token, index) => {
            const tokenStyle = { "--index": index } as CSSProperties;
            return (
              <Fragment key={index}>
                {index > 0 ? " " : null}
                {token.kind === "word" ? (
                  <span className={styles.token} style={tokenStyle}>
                    {token.text}
                  </span>
                ) : (
                  <span className={styles.token} style={tokenStyle}>
                    <span className="sr-only">{t("citation", { number: token.number })}</span>
                    <CitationMark aria-hidden number={token.number} className="align-[0.1em]" />
                    {token.trailing}
                  </span>
                )}
              </Fragment>
            );
          })}
          <span aria-hidden className={styles.caret} />
        </p>
        <ol
          className={cn(
            "text-ink-soft mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs",
            styles.sources,
          )}
        >
          <SourceLine number={1} label={t("sources.first")} />
          <SourceLine number={2} label={t("sources.second")} />
        </ol>
      </div>
    </div>
  );
}

function SourceLine({ number, label }: { number: number; label: string }) {
  return (
    <li className="inline-flex items-center gap-2">
      <CitationMark number={number} />
      {label}
    </li>
  );
}

/** The pen dot that marks the question on the map, repeated here to tie the two together. */
function QuestionDot() {
  return (
    <svg aria-hidden viewBox="0 0 20 20" className="mt-px size-5 flex-none">
      <circle cx="10" cy="10" r="8.5" fill="none" className="stroke-pen" strokeWidth="1.5" />
      <circle cx="10" cy="10" r="4" className="fill-pen" />
    </svg>
  );
}
