import "server-only";
import { cookies } from "next/headers";
import { DEV_PREFIX, PROFILE_COOKIE, SESSION_COOKIE, parseDevUser } from "./session-consts";
import { readProfile, readSession, sessionSecret } from "./session-token";

export const isDev = process.env.NODE_ENV === "development";

/** Аккаунт текущего пользователя (user_id из гостевой сессии) или null, если сессии нет. */
export async function getUserId(): Promise<number | null> {
  const jar = await cookies();
  const raw = jar.get(SESSION_COOKIE)?.value;
  if (!raw) return null;
  if (isDev && raw.startsWith(DEV_PREFIX)) return parseDevUser(raw.slice(DEV_PREFIX.length));
  return readSession(raw, sessionSecret(process.env));
}

/** Активный профиль аккаунта: выбранный в переключателе (подписанный cookie) или основной — «я» с тем же id, что у аккаунта. */
export async function getProfileId(): Promise<number | null> {
  const uid = await getUserId();
  if (!uid) return null;
  const raw = (await cookies()).get(PROFILE_COOKIE)?.value;
  return readProfile(raw, uid, sessionSecret(process.env)) ?? uid;
}
