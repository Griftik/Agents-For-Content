import "server-only";
import { cookies } from "next/headers";
import { DEV_PREFIX, SESSION_COOKIE, parseDevUser, readSession, sessionSecret } from "./session-token";

export const isDev = process.env.NODE_ENV === "development";

/** Telegram id текущего пользователя или null, если сессии нет. */
export async function getUserId(): Promise<number | null> {
  const jar = await cookies();
  const raw = jar.get(SESSION_COOKIE)?.value;
  if (!raw) return null;
  if (isDev && raw.startsWith(DEV_PREFIX)) return parseDevUser(raw.slice(DEV_PREFIX.length));
  return readSession(raw, sessionSecret(process.env));
}
