import type { EventT } from "@/lib/api-types";
import { dateLong, placeLine, priceLabel, timeRange, wdShort } from "@/lib/format";


function Badges({ ev }: { ev: EventT }) {
  return (
    <>
      {ev.free ? <span className="badge free">бесплатно</span> : null}
      {ev.confidence === "нужно проверить" ? <span className="badge check">нужно проверить</span> : null}
    </>
  );
}

/** Публичная карточка события: заголовок, факты, описание, «Почему стоит». Общая для /e/<слаг> и приглашения. */
export function PublicEvent({ ev, heading = "h1" }: { ev: EventT; heading?: "h1" | "h2" }) {
  const { venue, rest } = placeLine(ev);
  const price = priceLabel(ev);
  const dates = [...ev.dates].sort();
  const shownDates = dates.slice(0, 6);
  const sourceOk = /^https?:\/\//.test(ev.url);
  const H = heading;
  return (
    <article className="stack" style={{ gap: 14 }}>
      <div className="fcover" style={{ borderRadius: "var(--r-card)", aspectRatio: "16 / 7" }}>
        <span className="svc cat">{ev.category}</span>
      </div>
      <div className="row"><Badges ev={ev} /></div>
      <H style={heading === "h2" ? { fontSize: 28 } : undefined}>{ev.title}</H>
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
    </article>
  );
}
