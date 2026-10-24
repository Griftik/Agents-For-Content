import type { Profile } from "./api-types";

/**
 * Повтор предложения подборки (T-INVITE-OFFER, «повтор»): API ставит offer_due = день события + 1 при принятии приглашения.
 * Показываем один раз (offer_seen < 2), когда срок настал и онбординг не пройден.
 */
export function offerAgain(p: Pick<Profile, "onboarded" | "offer_due" | "offer_seen">, today: string): boolean {
  return !p.onboarded && !!p.offer_due && p.offer_due <= today && (p.offer_seen ?? 0) < 2;
}
