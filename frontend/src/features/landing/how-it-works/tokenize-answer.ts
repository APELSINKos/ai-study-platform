export type AnswerToken =
  { kind: "word"; text: string } | { kind: "citation"; number: number; trailing: string };

/** A source mark like `[2]`, optionally followed by punctuation: `[2].` */
const CITATION = /^\[(\d+)\](\S*)$/;

/**
 * Splits an answer into the words and source marks it is typed out with. Words keep their own
 * punctuation; a mark keeps what follows it, so `slower [1],` gives a word, a mark and a comma.
 */
export function tokenizeAnswer(text: string): AnswerToken[] {
  return text
    .split(/\s+/)
    .filter(Boolean)
    .map((piece) => {
      const match = CITATION.exec(piece);
      if (match) {
        return { kind: "citation", number: Number(match[1]), trailing: match[2] ?? "" };
      }
      return { kind: "word", text: piece };
    });
}
