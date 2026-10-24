// Без node:crypto: файл подключается и в middleware (edge runtime).
export const SESSION_COOKIE = "leisure_session";
export const DEV_PREFIX = "dev:";

/** Значение dev-cookie допустимо только при NODE_ENV=development. */
export function parseDevUser(value: string | null | undefined): number | null {
  if (!value || !/^\d{1,15}$/.test(value)) return null;
  const n = Number(value);
  return n > 0 ? n : null;
}
