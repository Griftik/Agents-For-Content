import { NextResponse, type NextRequest } from "next/server";
import { setRef } from "@/lib/cookies";
import { CODE_RE } from "@/lib/start-param";

export const dynamic = "force-dynamic";

/** Клиентский слой сохраняет код рекомендации `ref_<код>` из start_param в cookie; при первом касании профиля он уходит в API. */
export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => ({}))) as { code?: unknown };
  const code = typeof body.code === "string" ? body.code : "";
  if (!CODE_RE.test(code)) return NextResponse.json({ ok: false }, { status: 400 });
  await setRef(code);
  return NextResponse.json({ ok: true }, { headers: { "Cache-Control": "no-store" } });
}
