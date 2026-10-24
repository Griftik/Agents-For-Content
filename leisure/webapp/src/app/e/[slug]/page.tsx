import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { cache } from "react";
import { Badges } from "@/components/EventCard";
import { ApiDown } from "@/components/Gate";
import { ApiError, api } from "@/lib/api";
import { botLink } from "@/lib/config";
import { dateLong, placeLine, priceLabel, timeRange, wdShort } from "@/lib/format";

export const dynamic = "force-dynamic";

const getEvent = cache(async (slug: string) => {
  try {
    return { ev: await api.event(slug), error: null as string | null };
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return { ev: null, error: null };
    if (e instanceof ApiError) return { ev: null, error: e.status ? String(e.status) : "нет связи" };
    throw e;
  }
});

type Props = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const { ev } = await getEvent(slug);
  if (!ev) return { title: "Событие" };
  const desc = (ev.why_fit_hint || ev.description || "").slice(0, 200);
  return {
    title: ev.title,
    description: desc,
    robots: { index: true, follow: true },
    openGraph: { title: ev.title, description: desc, type: "article", locale: "ru_RU" },
  };
}

export default async function EventPage({ params }: Props) {
  const { slug } = await params;
  if (!/^[A-Za-z0-9_-]{1,120}$/.test(slug)) notFound();
  const { ev, error } = await getEvent(slug);
  if (error) return <ApiDown message={error} />;
  if (!ev) notFound();

  const { venue, rest } = placeLine(ev);
  const price = priceLabel(ev);
  const dates = [...ev.dates].sort();
  const shownDates = dates.slice(0, 6);
  const moscowToday = new Date(Date.now() + 3 * 3600_000).toISOString().slice(0, 10);
  const past = dates.length > 0 && dates[dates.length - 1] < moscowToday;
  const cta = botLink(`e_${slug}`);
  const sourceOk = /^https?:\/\//.test(ev.url);

  return (
    <div className="wrap">
      <main id="main" className="public">
        <article className="stack" style={{ gap: 14 }}>
          <div className="row"><span className="eyebrow">{ev.category}</span><Badges ev={ev} /></div>
          <h1>{ev.title}</h1>
          {past ? <p className="notice warn" role="status">Это событие уже прошло. Подборку на ближайшие выходные можно собрать ниже.</p> : null}
          <dl className="facts">
            {dates.length ? (
              <>
                <dt>Когда</dt>
                <dd className="num">
                  {shownDates.map((d) => `${wdShort(d)}, ${dateLong(d)}`).join(" · ")}{dates.length > shownDates.length ? ` · и ещё ${dates.length - shownDates.length}` : ""}
                  {timeRange(ev) ? <><br />{timeRange(ev)}</> : null}
                  {ev.time_text && ev.time_text.length > 11 && ev.time_text !== timeRange(ev) ? <><br /><span className="muted">Расписание: {ev.time_text}</span></> : null}
                </dd>
              </>
            ) : null}
            {venue ? <><dt>Где</dt><dd><b>{venue}</b>{rest ? <><br />{rest}</> : null}</dd></> : null}
            {price || ev.price_text ? <><dt>Цена</dt><dd>{ev.price_text && ev.price_text !== price ? ev.price_text : price}</dd></> : null}
            {sourceOk ? <><dt>Источник</dt><dd><a href={ev.url} rel="nofollow noopener noreferrer" target="_blank">{new URL(ev.url).hostname.replace(/^www\./, "")}</a></dd></> : null}
          </dl>
          {ev.description ? <p style={{ maxWidth: "70ch", fontSize: 16 }}>{ev.description}</p> : null}
          {ev.why_fit_hint ? <p className="fit" style={{ maxWidth: "70ch" }}><span className="eyebrow">Почему стоит · </span>{ev.why_fit_hint}</p> : null}
        </article>

        <section className="cta" aria-labelledby="cta">
          <h2 id="cta">Собери свою подборку на выходные</h2>
          <p>Ответь боту на пару вопросов о том, что для тебя важно, и каждый четверг получай события с пояснением, почему они подходят именно тебе.</p>
          {cta ? <a className="btn primary" href={cta} rel="noopener noreferrer">Собрать мне такую подборку</a> : <p>Бот пока не подключён к этой странице.</p>}
        </section>

        <p className="foot"><a href="/policy">Политика обработки данных</a></p>
      </main>
    </div>
  );
}
