import { createHmac, timingSafeEqual } from "node:crypto";

export { DEV_PREFIX, SESSION_COOKIE, parseDevUser } from "./session-consts";

/** Подписанный токен сессии в cookie: `<id>.<exp>.<подпись>`. Выдаётся после проверки initData. */

export const SESSION_TTL_SEC = 24 * 60 * 60;

/** Секрет сессии: SESSION_SECRET, а если не задан — производный от токена бота (отдельный контекст, не ключ initData). */
export function sessionSecret(env: Record<string, string | undefined>): string | null {
  if (env.SESSION_SECRET) return env.SESSION_SECRET;
  if (env.LEISURE_BOT_TOKEN) return createHmac("sha256", env.LEISURE_BOT_TOKEN).update("leisure-web-session").digest("hex");
  return null;
}

function mac(secret: string, body: string): string {
  return createHmac("sha256", secret).update(body).digest("base64url");
}

export function issueSession(userId: number, secret: string, now = Math.floor(Date.now() / 1000)): { token: string; exp: number } {
  const exp = now + SESSION_TTL_SEC;
  const body = `${userId}.${exp}`;
  return { token: `${body}.${mac(secret, body)}`, exp };
}

export function readSession(token: string | undefined, secret: string | null, now = Math.floor(Date.now() / 1000)): number | null {
  if (!token || !secret) return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  const [id, exp, sig] = parts;
  const want = Buffer.from(mac(secret, `${id}.${exp}`));
  const got = Buffer.from(sig);
  if (got.length !== want.length || !timingSafeEqual(got, want)) return null;
  const expN = Number(exp);
  const idN = Number(id);
  if (!Number.isInteger(expN) || expN < now) return null;
  return Number.isSafeInteger(idN) && idN > 0 ? idN : null;
}
