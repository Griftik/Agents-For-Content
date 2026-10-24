import { NextResponse, type NextRequest } from "next/server";
import { api } from "@/lib/api";
import { parseToday } from "@/lib/format";

export const dynamic = "force-dynamic";

/** Файл календаря: ссылки .ics из API ведут сюда, дальше запрос уходит к API с ключом. */
export async function GET(req: NextRequest, ctx: { params: Promise<{ slug: string }> }) {
  const { slug } = await ctx.params;
  if (!/^[A-Za-z0-9_-]{1,120}$/.test(slug)) return new NextResponse("Не найдено", { status: 404 });
  const day = parseToday(req.nextUrl.searchParams.get("day") ?? undefined);
  const upstream = await api.ics(slug, day).catch(() => null);
  if (!upstream || !upstream.ok) return new NextResponse("Не найдено", { status: upstream?.status === 404 ? 404 : 502 });
  return new NextResponse(await upstream.text(), {
    headers: {
      "Content-Type": "text/calendar; charset=utf-8",
      "Content-Disposition": `attachment; filename="${slug}.ics"`,
      "Cache-Control": "private, max-age=300",
    },
  });
}
