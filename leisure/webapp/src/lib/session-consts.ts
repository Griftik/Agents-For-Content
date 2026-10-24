// Без node:crypto: файл подключается и в middleware (edge runtime).
export const SESSION_COOKIE = "leisure_session";
export const DEV_PREFIX = "dev:";

/** Значение dev-cookie допустимо только при NODE_ENV=development. */
export function parseDevUser(value: string | null | undefined): number | null {
  if (!value || !/^\d{1,15}$/.test(value)) return null;
  const n = Number(value);
  return n > 0 ? n : null;
}

/** Код рекомендации `ref_<код>` из start_param: живёт до первого касания профиля. */
export const REF_COOKIE = "leisure_ref";
/** Имя и username из Telegram (для записи приглашённого и пустого профиля); не секрет, подпись не нужна. */
export const WHO_COOKIE = "leisure_who";
/** «Потом» на предложении подборки: день события, после которого предложение показывается ещё раз. */
export const OFFER_COOKIE = "leisure_offer";

/** Атрибуты cookie. В вебе Telegram Mini App живёт во фрейме: в production нужны SameSite=None и Partitioned. */
export function cookieOpts(maxAgeSec: number, prod: boolean) {
  return { httpOnly: true, path: "/", maxAge: maxAgeSec, secure: prod, sameSite: (prod ? "none" : "lax") as "none" | "lax", partitioned: prod };
}
