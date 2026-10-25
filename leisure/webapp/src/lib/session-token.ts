import { createHmac, timingSafeEqual } from "node:crypto";

export { DEV_PREFIX, SESSION_COOKIE, parseDevUser } from "./session-consts";

/** Подписанный токен сессии в cookie: `<id>.<exp>.<подпись>`. user_id выдаёт API (POST /api/session), подписывает веб. */

import { SESSION_TTL_SEC } from "./session-consts";
export { SESSION_TTL_SEC };

/** Секрет подписи: только SESSION_SECRET. Без него сессии не выдаются (в dev без секрета действует dev-режим `?dev_user=`). */
export function sessionSecret(env: Record<string, string | undefined>): string | null {
  return env.SESSION_SECRET || null;
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

/**
 * Активный профиль внутри аккаунта: `<profile_id>.<account_id>.<подпись>`. Подпись связывает профиль с аккаунтом, поэтому
 * подменить cookie на чужой профиль нельзя; список своих профилей при выборе проверяет сервер.
 */
export function issueProfile(profileId: number, accountId: number, secret: string): string {
  const body = `${profileId}.${accountId}`;
  return `${body}.${mac(secret, `profile:${body}`)}`;
}

export function readProfile(token: string | undefined, accountId: number, secret: string | null): number | null {
  if (!token || !secret) return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  const [pid, acc, sig] = parts;
  if (Number(acc) !== accountId) return null;
  const want = Buffer.from(mac(secret, `profile:${pid}.${acc}`));
  const got = Buffer.from(sig);
  if (got.length !== want.length || !timingSafeEqual(got, want)) return null;
  const n = Number(pid);
  return Number.isSafeInteger(n) && n > 0 ? n : null;
}
