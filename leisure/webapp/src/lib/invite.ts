// Правила экрана приглашения. Одни и те же функции решают, что показать на странице, и считают нажатия приглашённого:
// так число в README и в тесте не расходится с интерфейсом.

export type ProfileState = "new" | "onboarded";

export type Viewer = {
  /** Согласие на обработку данных уже дано (profile.has_consent). */
  hasConsent: boolean;
};

/** Галочку согласия показываем, пока согласия нет. */
export const needsConsent = (v: Pick<Viewer, "hasConsent">): boolean => !v.hasConsent;

export type Tap = "link" | "consent" | "accept";

/**
 * Нажатия приглашённого до записанного «иду»: переход по ссылке считается за одно. Гостевая сессия создаётся сама, входа нет.
 * Порядок «галочка, кнопка» и «кнопка, галочка» даёт те же два нажатия на странице.
 */
export function inviteeTaps(v: Viewer): Tap[] {
  const taps: Tap[] = ["link"];
  if (needsConsent(v)) taps.push("consent");
  taps.push("accept");
  return taps;
}

export const MAX_TAPS_TO_GOING = 3;

/** Статус решения в API приглашений → статус решения в профиле. */
export const DECISION_OF: Record<"going" | "maybe", "иду" | "может"> = { going: "иду", maybe: "может" };
