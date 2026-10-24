import { decide } from "@/app/actions";
import type { Decision, DigestItem } from "@/lib/api-types";
import { dateShort, priceLabel, shareUrl, wdFull } from "@/lib/format";
import { Ring } from "./Ring";

export function SlotCard({ item, decision, base }: { item: DigestItem; decision?: Decision; base: string }) {
  const ev = item.event;
  const cur = decision?.status;
  const chosen = cur === "иду" || item.chosen;
  const price = priceLabel(ev);
  const meta = [ev.venue, ev.time_text, ev.free ? "" : price].filter(Boolean);
  const day = item.day ?? ev.dates[0] ?? "";
  return (
    <article className="slot">
      <div className="eyebrow">{day ? `${wdFull(day)}, ${dateShort(day)}` : item.slot} · {item.slot}</div>
      <h3><a href={`/e/${ev.slug}`}>{ev.title}</a></h3>
      <p className="meta">{meta.join(" · ")}{ev.free ? <>{meta.length ? " · " : ""}<span className="free">бесплатно</span></> : null}</p>
      {item.why.length ? <div className="row">{item.why.map((w) => <span key={w.t} className={w.c === "learn" ? "why learn" : w.c === "neg" ? "why neg" : "why"}>{w.t}</span>)}</div> : null}
      <form action={decide} className="slot-foot">
        <input type="hidden" name="slug" value={ev.slug} />
        <input type="hidden" name="current" value={cur ?? ""} />
        <input type="hidden" name="op" value="toggle" />
        {day && !chosen ? <input type="hidden" name="day" value={day} /> : null}
        {item.score != null ? <Ring score={item.score} size={42} /> : <span />}
        <span className="row">
          <button type="submit" name="status" value="иду" className="btn small go" aria-pressed={chosen}>Иду</button>
          <button type="submit" name="status" value="пропуск" className="btn small" aria-pressed={cur === "пропуск"}>Другое</button>
          <button type="submit" name="status" value="мимо" className="btn small skip" aria-pressed={cur === "мимо"}>Не моё</button>
          <a className="btn small" href={shareUrl(ev, day, base)} target="_blank" rel="noopener noreferrer">Другу</a>
        </span>
      </form>
    </article>
  );
}
