import type { Metadata } from "next";
import { api } from "@/lib/api";
import type { Decision, ScoredEvent } from "@/lib/api-types";
import { webBaseUrl } from "@/lib/config";
import { first, isHorizon, parseToday, dateShort, wdShort, wdFull } from "@/lib/format";
import { load } from "@/lib/load";
import { getUserId, isDev } from "@/lib/session";
import { ApiDown, AuthGate, NoProfile } from "@/components/Gate";
import { EventCard } from "@/components/EventCard";
import { Masthead } from "@/components/Masthead";
import { SlotCard } from "@/components/SlotCard";

export const metadata: Metadata = { title: "Дайджест" };
export const dynamic = "force-dynamic";

const PAGE = 20;
type SP = Record<string, string | string[] | undefined>;

export default async function DigestPage({ searchParams }: { searchParams: Promise<SP> }) {
  const sp = await searchParams;
  const uid = await getUserId();
  if (!uid) return <AuthGate />;

  const today = isDev ? parseToday(first(sp.today)) : undefined;
  const loaded = await load(() =>
    Promise.all([api.digest(uid, today), api.digestAll(uid, today), api.decisions(uid), api.catalog(), api.profile(uid)]),
  );
  if (loaded.kind === "no-profile") return <NoProfile />;
  if (loaded.kind === "down") return <ApiDown message={loaded.message} />;
  const [digest, all, decList, catalog, profile] = loaded.data;
  const base = await webBaseUrl();

  const decisions = new Map<string, Decision>(decList.map((d) => [d.event_slug, d]));
  const weekend = digest.weekend;

  // фильтры
  const day = first(sp.day) ?? "";
  const cat = first(sp.cat) ?? "";
  const onlyFree = first(sp.free) === "1";
  const hideSkipped = first(sp.hide) === "1";
  const limit = Math.min(500, Math.max(PAGE, Number(first(sp.limit)) || PAGE));
  const href = (over: Record<string, string | undefined>) => {
    const cur: Record<string, string | undefined> = { day, cat, free: onlyFree ? "1" : "", hide: hideSkipped ? "1" : "", today: isDev ? first(sp.today) : "" };
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries({ ...cur, ...over })) if (v) q.set(k, v);
    const s = q.toString();
    return `/digest${s ? `?${s}` : ""}`;
  };

  const inDay = (e: ScoredEvent, d: string) => (d === "horizon" ? isHorizon(e, weekend) : e.dates.includes(d));
  const dayCounts = weekend.map((d) => all.filter((e) => e.dates.includes(d)).length);
  const horizonCount = all.filter((e) => isHorizon(e, weekend)).length;

  const catCounts = new Map<string, number>();
  for (const e of all) catCounts.set(e.category, (catCounts.get(e.category) ?? 0) + 1);
  const cats = [...catCounts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "ru"));

  const shown = all.filter(
    (e) =>
      (!day || inDay(e, day)) &&
      (!cat || e.category === cat) &&
      (!onlyFree || e.free) &&
      (!hideSkipped || decisions.get(e.slug)?.status !== "мимо"),
  );
  const page = shown.slice(0, limit);
  const dayForActions = weekend.includes(day) ? day : undefined;

  const daysWithItems = new Set(digest.items.map((i) => i.day));
  const emptyDays = weekend.filter((d) => !daysWithItems.has(d));

  return (
    <div className="wrap">
      <Masthead eyebrow="Подборка на выходные" title="Уикенд" accent={digest.title} tab="digest" digestCount={all.length} name={profile.name || undefined} />
      <main id="main" className="page" style={{ paddingTop: 18 }}>
        <section className="stack" aria-labelledby="rec">
          <div className="sec"><h2 id="rec">Рекомендация</h2><span>{digest.items.length} из 5 слотов</span></div>
          {emptyDays.length ? (
            <p className="empty">
              {emptyDays.map((d, i) => (i === 0 ? wdFull(d) : wdFull(d).toLowerCase())).join(", ")} — свободно. Под твои интересы ничего не нашлось, смотри полный список ниже.
            </p>
          ) : null}
          {digest.items.map((it) => (
            <SlotCard key={`${it.day}-${it.slot}-${it.event.slug}`} item={it} decision={decisions.get(it.event.slug)} base={base} />
          ))}
          {digest.horizon.length ? (
            <>
              <div className="sec"><h2 style={{ fontSize: 22 }}>На горизонте</h2><span>дальше этих выходных</span></div>
              {digest.horizon.map((it) => (
                <SlotCard key={`h-${it.event.slug}`} item={it} decision={decisions.get(it.event.slug)} base={base} />
              ))}
            </>
          ) : null}
        </section>

        <section aria-labelledby="all">
          <div className="sec"><h2 id="all">Весь список</h2><span className="num">{shown.length} из {all.length}</span></div>
          <div className="filters" style={{ marginTop: 12 }}>
            <nav className="chips" aria-label="День">
              <a className="chip day" href={href({ day: "", limit: "" })} aria-current={!day ? "true" : undefined}>Все дни</a>
              {weekend.map((d, i) => (
                <a key={d} className="chip day" href={href({ day: d, limit: "" })} aria-current={day === d ? "true" : undefined}>
                  {wdShort(d)[0].toUpperCase() + wdShort(d).slice(1)} {dateShort(d).split(" ")[0]} <span className="n">{dayCounts[i]}</span>
                </a>
              ))}
              <a className="chip day" href={href({ day: "horizon", limit: "" })} aria-current={day === "horizon" ? "true" : undefined}>
                Горизонт <span className="n">{horizonCount}</span>
              </a>
            </nav>
            <nav className="chips" aria-label="Направление">
              <a className="chip" href={href({ cat: "", limit: "" })} aria-current={!cat ? "true" : undefined}>Все направления</a>
              {cats.map(([name, n]) => (
                <a key={name} className="chip" href={href({ cat: name, limit: "" })} aria-current={cat === name ? "true" : undefined}>
                  {name} <span className="n">{n}</span>
                </a>
              ))}
            </nav>
            <nav className="chips" aria-label="Дополнительно">
              <a className="chip" href={href({ free: onlyFree ? "" : "1", limit: "" })} aria-current={onlyFree ? "true" : undefined}>Бесплатно</a>
              <a className="chip" href={href({ hide: hideSkipped ? "" : "1", limit: "" })} aria-current={hideSkipped ? "true" : undefined}>Скрыть «мимо»</a>
            </nav>
          </div>

          {page.length ? (
            <div className="list" style={{ marginTop: 6 }}>
              {page.map((e) => (
                <EventCard key={e.slug} ev={e} why={e.why} score={e.score} decision={decisions.get(e.slug)} weekend={weekend}
                  reasons={catalog.reasons} base={base} day={dayForActions} />
              ))}
            </div>
          ) : (
            <p className="empty" style={{ marginTop: 14 }}>Под эти фильтры ничего нет. <a href="/digest">Сбросить фильтры</a></p>
          )}
          {shown.length > page.length ? (
            <p className="more"><a className="btn" href={href({ limit: String(limit + PAGE) })}>Показать ещё {Math.min(PAGE, shown.length - page.length)}</a></p>
          ) : null}
        </section>
      </main>
    </div>
  );
}
