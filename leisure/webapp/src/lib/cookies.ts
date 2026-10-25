import "server-only";
import { cookies } from "next/headers";
import { PROFILE_COOKIE, REF_COOKIE, SESSION_COOKIE, cookieOpts } from "./session-consts";
import { CODE_RE } from "./start-param";

const prod = () => process.env.NODE_ENV === "production";
const DAY = 24 * 60 * 60;

export async function readRef(): Promise<string | null> {
  const v = (await cookies()).get(REF_COOKIE)?.value;
  return v && CODE_RE.test(v) ? v : null;
}
export async function setRef(code: string) {
  (await cookies()).set(REF_COOKIE, code, cookieOpts(14 * DAY, prod()));
}
export async function clearCookie(name: string) {
  (await cookies()).set(name, "", { ...cookieOpts(0, prod()), maxAge: 0 });
}
export async function setSessionCookie(token: string, maxAgeSec: number) {
  (await cookies()).set(SESSION_COOKIE, token, cookieOpts(maxAgeSec, prod()));
}
export async function setProfileCookie(token: string) {
  (await cookies()).set(PROFILE_COOKIE, token, cookieOpts(180 * DAY, prod()));
}
