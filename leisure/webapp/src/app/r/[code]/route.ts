import { NextResponse } from "next/server";
import { ApiError, api } from "@/lib/api";
import { setRef } from "@/lib/cookies";
import { CODE_RE } from "@/lib/start-param";

export const dynamic = "force-dynamic";

const go = (to: string) => new NextResponse(null, { status: 303, headers: { Location: to, "Cache-Control": "no-store" } });

/** Ссылка-рекомендация `/r/<код>`: код проверяется в API и запоминается в cookie, дальше приветствие. Битый код — приветствие с пометкой. */
export async function GET(_req: Request, ctx: { params: Promise<{ code: string }> }) {
  const { code } = await ctx.params;
  if (!CODE_RE.test(code)) return go("/profile?onboarding=welcome&bad_ref=1");
  try {
    const inv = await api.invite(code);
    if (inv.kind !== "ref" && inv.kind !== "event") return go("/profile?onboarding=welcome&bad_ref=1");
    if (inv.kind === "event" && inv.event_slug) return go(`/e/${encodeURIComponent(inv.event_slug)}?inv=${code}`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return go("/profile?onboarding=welcome&bad_ref=1");
    if (!(e instanceof ApiError)) throw e;
    // API недоступен: код всё равно запомним, профиль создастся позже
  }
  await setRef(code);
  // относительный Location: за прокси внутренний адрес сервера наружу не попадает
  return go("/profile?onboarding=welcome");
}
