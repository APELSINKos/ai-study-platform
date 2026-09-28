/** The sample deck of the landing demo; texts live in `Landing.practice.cards`. */
export const SAMPLE_CARDS = ["measure", "spacing", "testing", "interference"] as const;
export type SampleCard = (typeof SAMPLE_CARDS)[number];

/**
 * The four answers to "how well did you remember?", in button order. Their example intervals
 * (10 minutes to 5 days) are what the scheduler gives a card seen for the first time.
 */
export const RATINGS = ["again", "hard", "good", "easy"] as const;
export type Rating = (typeof RATINGS)[number];

export function cardAt(position: number): SampleCard {
  return SAMPLE_CARDS[position % SAMPLE_CARDS.length] ?? SAMPLE_CARDS[0];
}

export function nextPosition(position: number): number {
  return (position + 1) % SAMPLE_CARDS.length;
}

/** The rating a number key stands for: 1 is "again" and 4 is "easy". */
export function ratingForKey(key: string): Rating | null {
  if (!/^[1-9]$/.test(key)) {
    return null;
  }
  return RATINGS[Number(key) - 1] ?? null;
}
