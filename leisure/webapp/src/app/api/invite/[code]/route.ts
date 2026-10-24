import { NextResponse } from "next/server";
import { ApiError, api } from "@/lib/api";
import { CODE_RE } from "@/lib/start-param";

export const dynamic = "force-dynamic";

/** Для клиентского слоя: по коду из start_param узнать слаг события (GET /api/invites/{code}); ключ API остаётся на сервере. */
export async function GET(_req: Request, ctx: { params: Promise<{ code: string }> }) {
  const { code } = await ctx.params;
  if (!CODE_RE.test(code)) return NextResponse.json({ ok: false, error: "bad_code" }, { status: 400 });
  try {
    const inv = await api.invite(code);
    return NextResponse.json({ ok: true, slug: inv.event?.slug ?? null, status: inv.status }, { headers: { "Cache-Control": "no-store" } });
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return NextResponse.json({ ok: false, error: "not_found" }, { status: 404 });
    return NextResponse.json({ ok: false, error: "unavailable" }, { status: 502 });
  }
}
