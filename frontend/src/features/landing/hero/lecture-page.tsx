import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

import styles from "./lecture-page.module.css";

/** A page of printed lecture notes that a student marks up while the hero loads. */
export function LecturePage({ className }: { className?: string }) {
  const t = useTranslations("Landing.hero.page");

  return (
    // Purely an illustration: the hero text says the same thing in words.
    <div aria-hidden className={cn(styles.frame, className)}>
      <div className={styles.page}>
        <p className={styles.course}>{t("course")}</p>
        <p className={styles.title}>{t("title")}</p>
        <div className={styles.body}>
          <p className={styles.line}>{t("intro1")}</p>
          <p className={styles.line}>{t("intro2")}</p>
          <MarkedLine text={t("marked1")} className={styles.first} />
          <MarkedLine text={t("marked2")} className={styles.second} />
          <p className={styles.line}>{t("outro")}</p>
          <p className={styles.note}>
            <svg className={styles.bracket} viewBox="0 0 12 51">
              <path
                className={styles.stroke}
                pathLength={1}
                d="M2 2C8 3 7 13 7 20c0 3 1 5.5 4 5.5-3 0-4 2.5-4 5.5 0 7 1 17-5 18"
              />
            </svg>
            <svg className={styles.arrow} viewBox="0 0 28 22">
              <path
                className={styles.stroke}
                pathLength={1}
                d="M26 19C17 19 9 15 6 5m0 0L3 11m3-6 5 4"
              />
            </svg>
            <span className={styles.noteText}>{t("note")}</span>
          </p>
        </div>
      </div>
    </div>
  );
}

function MarkedLine({ text, className }: { text: string; className?: string }) {
  return (
    <p className={cn(styles.marked, className)}>
      <span className={styles.ink}>{text}</span>
      <span className={styles.marker}>{text}</span>
    </p>
  );
}
