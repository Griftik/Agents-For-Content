import { NextResponse } from "next/server";
import { ApiError, api } from "@/lib/api";
import { setSessionCookie } from "@/lib/cookies";
import { getUserId } from "@/lib/session";
import { SESSION_TTL_SEC, issueSession, sessionSecret } from "@/lib/session-token";

export const dynamic = "force-dynamic";

/**
 * Гостевая сессия с первого экрана: API выдаёт user_id (POST /api/session), веб подписывает его своим секретом и ставит
 * httpOnly-cookie на 180 дней. Повторный вызов с живой сессией ничего не создаёт.
 */
export async function POST() {
  if (await getUserId()) return NextResponse.json({ ok: true, created: false }, { headers: { "Cache-Control": "no-store" } });
  const secret = sessionSecret(process.env);
  if (!secret) return NextResponse.json({ ok: false, error: "server_not_configured" }, { status: 503 });
  try {
    const { user_id } = await api.createSession();
    if (!Number.isSafeInteger(user_id) || user_id <= 0) return NextResponse.json({ ok: false, error: "bad_session" }, { status: 502 });
    await setSessionCookie(issueSession(user_id, secret).token, SESSION_TTL_SEC);
    return NextResponse.json({ ok: true, created: true }, { headers: { "Cache-Control": "no-store" } });
  } catch (e) {
    if (e instanceof ApiError) return NextResponse.json({ ok: false, error: "unavailable" }, { status: 502 });
    throw e;
  }
}
