// Правила экрана приглашения. Одни и те же функции решают, что показать на странице, и считают нажатия приглашённого:
// так число в README и в тесте не расходится с интерфейсом.

export type ProfileState = "new" | "onboarded";

export type Viewer = {
  /** Страница открыта в Telegram (есть initData). В браузере без Telegram «иду» записать нельзя. */
  inTelegram: boolean;
  /** Профиль уже есть (значит, согласие на обработку данных дано). */
  hasProfile: boolean;
};

/** Галочку согласия показываем, пока профиля нет. */
export const needsConsent = (v: Pick<Viewer, "hasProfile">): boolean => !v.hasProfile;

export type Tap = "link" | "open-in-telegram" | "consent" | "accept";

/**
 * Нажатия приглашённого до записанного «иду» (FLOW-INVITE, раздел 6): переход по ссылке считается как /start.
 * Порядок «галочка, кнопка» и «кнопка, галочка» даёт те же два нажатия на странице.
 */
export function inviteeTaps(v: Viewer): Tap[] {
  const taps: Tap[] = ["link"];
  if (!v.inTelegram) taps.push("open-in-telegram");
  if (needsConsent(v)) taps.push("consent");
  taps.push("accept");
  return taps;
}

export const MAX_TAPS_TO_GOING = 3;

/** Статус решения в API приглашений → статус решения в профиле. */
export const DECISION_OF: Record<"going" | "maybe", "иду" | "может"> = { going: "иду", maybe: "может" };
