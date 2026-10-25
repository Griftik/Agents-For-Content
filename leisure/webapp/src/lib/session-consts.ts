// Без node:crypto: файл подключается и в middleware (edge runtime).
export const SESSION_COOKIE = "leisure_session";
export const DEV_PREFIX = "dev:";

/** Гостевая сессия живёт 180 дней: человек открывает приложение с экрана телефона без входа. */
export const SESSION_TTL_SEC = 180 * 24 * 60 * 60;

/** Значение dev-cookie допустимо только при NODE_ENV=development. */
export function parseDevUser(value: string | null | undefined): number | null {
  if (!value || !/^\d{1,15}$/.test(value)) return null;
  const n = Number(value);
  return n > 0 ? n : null;
}

/** Активный профиль аккаунта («я», «мама», «ребёнок»): подписанная пара <profile_id>.<account_id>. */
export const PROFILE_COOKIE = "leisure_profile";

/** Код рекомендации (`/r/<код>` или `/?ref=<код>`): живёт до первого касания профиля. */
export const REF_COOKIE = "leisure_ref";

/** Атрибуты cookie: первая сторона (приложение открыто на своём домене), HTTPS в production. */
export function cookieOpts(maxAgeSec: number, prod: boolean) {
  return { httpOnly: true, path: "/", maxAge: maxAgeSec, secure: prod, sameSite: "lax" as const };
}
