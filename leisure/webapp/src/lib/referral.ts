// Момент рекомендации: после оценки 4–5 в плане, не чаще раза в две недели.

export const REF_ASK_DAYS = 14;

/** Просьба о рекомендации: после оценки 4–5 и не чаще раза в две недели (docs/GROWTH.md §2.3). */
export function canAskReferral(rating: number, lastAskedAt: number | null, now: number): boolean {
  if (rating < 4) return false;
  return lastAskedAt == null || now - lastAskedAt >= REF_ASK_DAYS * 86400_000;
}
