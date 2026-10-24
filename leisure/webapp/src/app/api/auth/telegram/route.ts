import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE, issueSession, sessionSecret } from "@/lib/session-token";
import { verifyInitData } from "@/lib/telegram";

export const dynamic = "force-dynamic";

/** Клиентский слой присылает initData в заголовке; после проверки подписи и свежести выдаём cookie сессии. */
export async function POST(req: NextRequest) {
  const initData = req.headers.get("x-telegram-init-data");
  const botToken = process.env.LEISURE_BOT_TOKEN;
  const secret = sessionSecret(process.env);
  if (!botToken || !secret) {
    return NextResponse.json({ ok: false, error: "server_not_configured" }, { status: 503 });
  }
  const res = verifyInitData(initData, botToken);
  if (!res.ok) {
    return NextResponse.json({ ok: false, error: res.reason }, { status: 401, headers: { "Cache-Control": "no-store" } });
  }
  const { token, exp } = issueSession(res.user.id, secret);
  const out = NextResponse.json({ ok: true }, { headers: { "Cache-Control": "no-store" } });
  const prod = process.env.NODE_ENV === "production";
  out.cookies.set(SESSION_COOKIE, token, {
    httpOnly: true,
    path: "/",
    expires: new Date(exp * 1000),
    // Mini App в вебе Telegram живёт во фрейме: нужны SameSite=None и partitioned-cookie.
    secure: prod,
    sameSite: prod ? "none" : "lax",
    partitioned: prod,
  });
  return out;
}
