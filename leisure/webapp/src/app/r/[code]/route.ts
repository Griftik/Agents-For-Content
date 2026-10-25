import { NextResponse } from "next/server";
import { setRef } from "@/lib/cookies";
import { CODE_RE } from "@/lib/start-param";

export const dynamic = "force-dynamic";

/** Ссылка-рекомендация `/r/<код>`: код запоминается в cookie, дальше приветствие. При первом касании профиля код уходит в API. */
export async function GET(_req: Request, ctx: { params: Promise<{ code: string }> }) {
  const { code } = await ctx.params;
  if (CODE_RE.test(code)) await setRef(code);
  // относительный Location: за прокси внутренний адрес сервера наружу не попадает
  return new NextResponse(null, { status: 303, headers: { Location: "/profile?onboarding=welcome", "Cache-Control": "no-store" } });
}
