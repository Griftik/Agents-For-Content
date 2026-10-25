import type { EventT } from "@/lib/api-types";
import { dayLabel, timeLine } from "@/lib/feed";
import { moscowToday, placeLine, priceLabel } from "@/lib/format";

/**
 * Карточка-билет во всю страницу (DESIGN.md v2, EventPage): обложка только при фото, число-герой времени, название, место,
 * линия отрыва, описание, подвал с ценой и направлением. Общая для страницы события и приглашения.
 */
export function PublicEvent({ ev, day, heading = "h1", cover }: { ev: EventT; day?: string | null; heading?: "h1" | "h2"; cover?: string | null }) {
  const { venue, rest } = placeLine(ev);
  const price = priceLabel(ev);
  const today = moscowToday();
  const dates = [...ev.dates].sort();
  const d = day && ev.dates.includes(day) ? day : (dates.find((x) => x >= today) ?? dates[0] ?? null);
  const interval = ev.start_time && ev.end_time && ev.end_time !== ev.start_time ? `${ev.start_time}–${ev.end_time}` : "";
  const dayText = d ? timeLine(d, today, null, null) : "";
  const more = dates.filter((x) => x !== d && x >= today).slice(0, 4);
  const sourceOk = /^https?:\/\//.test(ev.url);
  const H = heading;
  return (
    <article className="ticket" aria-label={ev.title}>
      {cover ? (
        <div className="cover">
          {/* обложка с чужого домена источника: next/image требует список доменов */}
          <img src={cover} alt="" loading="lazy" /> {/* eslint-disable-line @next/next/no-img-element */}
        </div>
      ) : null}
      <div className="row" style={{ justifyContent: "space-between" }}>
        <span className="svc">{ev.category}</span>
        {ev.confidence === "нужно проверить" ? <span className="svc warn">Нужно проверить</span> : null}
        {d && d < today ? <span className="svc warn">Прошло</span> : null}
      </div>
      <div className="when">
        {ev.start_time ? <b>{ev.start_time}</b> : null}
        <span className="svc fg">{[dayText, interval].filter(Boolean).join(" · ")}</span>
      </div>
      <H>{ev.title}</H>
      <p className="place">{venue}{rest ? ` · ${rest}` : ""}</p>
      {more.length ? <span className="svc">Ещё: {more.map((x) => dayLabel(x as `${number}-${number}-${number}`)).join(" · ")}</span> : null}
      {ev.time_text && ev.time_text.length > 11 && !interval ? <span className="svc">{ev.time_text}</span> : null}
      <div className="tear" aria-hidden="true" />
      {ev.description ? <p className="desc">{ev.description}</p> : null}
      <div className="bot">
        <span className="svc">{[ev.free ? "Бесплатно" : (ev.price_text && ev.price_text !== price ? ev.price_text : price), sourceOk ? new URL(ev.url).hostname.replace(/^www\./, "") : ""].filter(Boolean).join(" · ")}</span>
      </div>
    </article>
  );
}
