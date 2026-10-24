import "server-only";
import { cookies } from "next/headers";
import { OFFER_COOKIE, REF_COOKIE, WHO_COOKIE, cookieOpts } from "./session-consts";
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

export type Who = { name: string; username: string };
export async function readWho(): Promise<Who> {
  try {
    const raw = (await cookies()).get(WHO_COOKIE)?.value;
    if (!raw) return { name: "", username: "" };
    const j = JSON.parse(Buffer.from(raw, "base64url").toString("utf8")) as { n?: unknown; u?: unknown };
    return { name: typeof j.n === "string" ? j.n.slice(0, 200) : "", username: typeof j.u === "string" ? j.u.slice(0, 100) : "" };
  } catch {
    return { name: "", username: "" };
  }
}
export const encodeWho = (name: string, username: string) =>
  Buffer.from(JSON.stringify({ n: name.slice(0, 200), u: username.slice(0, 100) }), "utf8").toString("base64url");

export async function readOffer(): Promise<string | null> {
  const v = (await cookies()).get(OFFER_COOKIE)?.value;
  return v && /^\d{4}-\d{2}-\d{2}$/.test(v) ? v : null;
}
export async function setOffer(day: string) {
  (await cookies()).set(OFFER_COOKIE, day, cookieOpts(60 * DAY, prod()));
}
