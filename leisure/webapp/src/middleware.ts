import { NextResponse, type NextRequest } from "next/server";
import { DEV_PREFIX, SESSION_COOKIE, parseDevUser } from "@/lib/session-consts";

/**
 * Режим разработки: ?dev_user=<id> без подписи ставит dev-cookie.
 * В production (NODE_ENV !== "development") middleware ничего не делает, а сам cookie не принимается.
 */
export function middleware(req: NextRequest) {
  if (process.env.NODE_ENV !== "development") return NextResponse.next();
  const uid = parseDevUser(req.nextUrl.searchParams.get("dev_user"));
  if (!uid) return NextResponse.next();

  const value = `${DEV_PREFIX}${uid}`;
  // Cookie нужен и текущему запросу (серверные компоненты читают его сразу), и браузеру на следующие.
  req.cookies.set(SESSION_COOKIE, value);
  const headers = new Headers(req.headers);
  headers.set("cookie", req.cookies.toString());
  const res = NextResponse.next({ request: { headers } });
  res.cookies.set(SESSION_COOKIE, value, { httpOnly: true, sameSite: "lax", path: "/" });
  return res;
}

export const config = { matcher: ["/((?!_next/|api/|favicon).*)"] };
