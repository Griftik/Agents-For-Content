import { decide } from "@/app/actions";
import type { Decision, EventT, Why } from "@/lib/api-types";
import { REASON_LABEL, dateShort, placeLine, priceLabel, shareUrl, startTime, wdShort, whenLabel } from "@/lib/format";
import { Ring } from "./Ring";

const whyClass = (w: Why) => (w.c === "learn" ? "why learn" : w.c === "neg" ? "why neg" : "why");

export function Badges({ ev }: { ev: EventT }) {
  return (
    <>
      {ev.free ? <span className="badge free">бесплатно</span> : null}
      {ev.confidence === "нужно проверить" ? <span className="badge check">нужно проверить</span> : null}
      {ev.confidence === "вероятно" ? <span className="badge">вероятно</span> : null}
    </>
  );
}

function Hidden({ ev, decision, op }: { ev: EventT; decision?: Decision; op?: "toggle" }) {
  return (
    <>
      <input type="hidden" name="slug" value={ev.slug} />
      <input type="hidden" name="current" value={decision?.status ?? ""} />
      {decision?.reason ? <input type="hidden" name="current_reason" value={decision.reason} /> : null}
      {decision?.day ? <input type="hidden" name="current_day" value={decision.day} /> : null}
      {op ? <input type="hidden" name="op" value={op} /> : null}
    </>
  );
}

/** Кнопки решений: одна форма, статус приходит в имени нажатой кнопки. */
export function DecisionButtons({ ev, decision, day, base, shareDay }: { ev: EventT; decision?: Decision; day?: string; base: string; shareDay?: string | null }) {
  const cur = decision?.status;
  const btn = (status: string, label: string, cls: string) => (
    <button type="submit" name="status" value={status} className={`btn ${cls}`} aria-pressed={cur === status}>{label}</button>
  );
  return (
    <form action={decide} className="row actions">
      <Hidden ev={ev} decision={decision} op="toggle" />
      {day && cur !== "иду" ? <input type="hidden" name="day" value={day} /> : null}
      {btn("иду", "Иду", "go")}
      {btn("может", "Может быть", "maybe")}
      {btn("интересно", "Интересно", "like")}
      {btn("мимо", "Мимо", "skip")}
      <a className="btn link" href={`/e/${ev.slug}`}>Подробнее</a>
      <a className="btn small" href={shareUrl(ev, shareDay ?? day, base)} target="_blank" rel="noopener noreferrer">Другу</a>
    </form>
  );
}

function FollowUp({ ev, decision, reasons, weekend }: { ev: EventT; decision?: Decision; reasons: string[]; weekend: string[] }) {
  const days = ev.dates.filter((d) => weekend.includes(d));
  return (
    <>
      {decision?.status === "мимо" ? (
        <form action={decide} className="reasons" aria-label="Почему мимо">
          <Hidden ev={ev} decision={decision} />
          <input type="hidden" name="status" value="мимо" />
          <span className="eyebrow">Почему мимо ·</span>
          {reasons.map((r) => (
            <button key={r} type="submit" name="reason" value={r} className="btn small" aria-pressed={decision.reason === r}>{REASON_LABEL[r] ?? r}</button>
          ))}
        </form>
      ) : null}
      {decision?.status === "иду" && days.length > 1 ? (
        <form action={decide} className="daypick" aria-label="В какой день идёшь">
          <Hidden ev={ev} decision={decision} />
          <input type="hidden" name="status" value="иду" />
          <span className="eyebrow">В какой день ·</span>
          {days.map((d) => (
            <button key={d} type="submit" name="day" value={d} className="btn small" aria-pressed={decision.day === d}>{wdShort(d)}, {dateShort(d)}</button>
          ))}
        </form>
      ) : null}
    </>
  );
}

export function EventCard({ ev, why, score, decision, weekend, reasons, base, day }: {
  ev: EventT;
  why?: Why[];
  score?: number | null;
  decision?: Decision;
  weekend: string[];
  reasons: string[];
  base: string;
  day?: string;
}) {
  const when = whenLabel(ev.dates, weekend);
  const { venue, rest } = placeLine(ev);
  const price = priceLabel(ev);
  const skipped = decision?.status === "мимо";
  return (
    <article className={`ev${skipped ? " skipped" : ""}`} id={`ev-${ev.slug}`}>
      <div className="when">
        <b className="num">{when.num}</b>
        <span>{when.sub}{startTime(ev) ? <><br />{startTime(ev)}</> : null}</span>
      </div>
      <div className="body">
        <div className="ev-head">
          <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 0 }}>
            <div className="row"><span className="eyebrow">{ev.category}</span><Badges ev={ev} /></div>
            <h3>
              <a href={`/e/${ev.slug}`}>{ev.title}</a>
              {decision?.status === "интересно" ? <span className="heart" role="img" aria-label="интересно">{"♥︎"}</span> : null}
            </h3>
          </div>
          {score != null ? <Ring score={score} /> : null}
        </div>
        <p className="place">
          <b>{venue}</b>{rest ? ` · ${rest}` : ""}{price && !ev.free ? ` · ${price}` : ""}
        </p>
        {ev.description ? <p className="desc" style={{ display: "-webkit-box", WebkitLineClamp: 4, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{ev.description}</p> : null}
        {why && why.length ? <div className="row">{why.map((w) => <span key={w.t} className={whyClass(w)}>{w.t}</span>)}</div> : null}
        {ev.why_fit_hint ? <p className="fit"><b>Почему тебе · </b>{ev.why_fit_hint}</p> : null}
        <DecisionButtons ev={ev} decision={decision} day={day} base={base} />
        <FollowUp ev={ev} decision={decision} reasons={reasons} weekend={weekend} />
      </div>
    </article>
  );
}
