import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { ApiDown, AuthGate, NoProfile } from "@/components/Gate";
import { DayStrip } from "@/components/DayStrip";
import { FeedDeck } from "@/components/FeedDeck";
import { Masthead } from "@/components/Masthead";
import { api } from "@/lib/api";
import type { AccountProfile } from "@/lib/api-types";
import { apiDate, dayLabel, parseDay, parseSegment } from "@/lib/feed";
import { first, moscowToday } from "@/lib/format";
import { load } from "@/lib/load";
import { hasUnmarkedPast } from "@/lib/plan";
import { getProfileId, getUserId } from "@/lib/session";

export const metadata: Metadata = { title: "Рекомендации" };
export const dynamic = "force-dynamic";

/** Главный экран: дни сверху, направление, лента крупных карточек из GET /api/feed. */
export default async function FeedPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const uid = await getUserId();
  const pid = await getProfileId();
  if (!uid || !pid) return <AuthGate />;
  const today = moscowToday();
  const seg = parseSegment(first(sp.seg));
  const dayRaw = parseDay(first(sp.day));
  const day = /^\d{4}-\d{2}-\d{2}$/.test(dayRaw) && dayRaw < today ? "today" : dayRaw; // прошедшая дата — показываем сегодня

  const loaded = await load(() =>
    Promise.all([api.profile(pid), api.feed(pid, apiDate(day, today), seg), api.profiles(uid).catch((): AccountProfile[] => []), api.decisions(pid)]),
  );
  if (loaded.kind === "no-profile") return <NoProfile />;
  if (loaded.kind === "down") return <ApiDown message={loaded.message} />;
  const [profile, feed, profiles, decisions] = loaded.data;
  if (!profile.has_consent) return <NoProfile />;
  if (!profile.onboarded) redirect("/profile?onboarding=1");
  const list = profiles.length ? profiles : [{ id: uid, name: profile.name || "я", kind: "self", onboarded: true }];
  // T-FEED-END / T-FEED-EMPTY / T-FEED-LATE: одна строка и одно действие
  const next = day === "today" ? `/digest?day=tomorrow&seg=${seg}` : day === "tomorrow" ? `/digest?day=day2&seg=${seg}` : day === "day2" ? `/digest?day=week&seg=${seg}` : null;
  const nextLabel = day === "today" ? "Завтра" : day === "tomorrow" ? "Послезавтра" : "Неделя";
  const lateToday = day === "today" && feed.items.length === 0 && new Date(Date.now() + 3 * 3600_000).getUTCHours() >= 20;
  const emptyLabel = lateToday ? "Сегодня уже поздно" : day === "today" ? "На сегодня всё" : day === "week" ? "На неделю всё" : "На этот день всё";

  return (
    <div className="wrap">
      <Masthead title={dayLabel(day)} tab="digest" profiles={list} activeId={pid} planDot={hasUnmarkedPast(decisions, today)} />
      <main id="main" className="page reveal feed-main" style={{ paddingTop: 4, gap: 12 }}>
        <DayStrip day={day} segment={seg} today={today} />
        <FeedDeck key={`${day}-${seg}`} items={feed.items} today={today} emptyLabel={emptyLabel} nextLabel={nextLabel} nextHref={next} />
      </main>
    </div>
  );
}
