import type { DayKey, Segment } from "@/lib/feed";
import { SEGMENTS, dayLabel } from "@/lib/feed";
import { DateInput } from "./DateInput";

const KEYS: DayKey[] = ["today", "tomorrow", "day2", "week"];

/** Дни и направление: обычные ссылки (работают без JS), выбранное — заливка и aria-current. Календарь — input type=date. */
export function DayStrip({ day, segment, today }: { day: DayKey; segment: Segment; today: string }) {
  const href = (d: DayKey, s: Segment) => `/digest?day=${d}&seg=${s}`;
  const custom = !KEYS.includes(day);
  return (
    <div className="stack" style={{ gap: 10 }}>
      <nav className="daystrip" aria-label="День">
        {KEYS.map((k) => (
          <a key={k} className="chip day" href={href(k, segment)} aria-current={day === k ? "true" : undefined}>{dayLabel(k)}</a>
        ))}
        {custom ? <a className="chip day" href={href(day, segment)} aria-current="true">{dayLabel(day)}</a> : null}
        <form method="get" action="/digest" className="chip cal" aria-label="Выбрать дату">
          <input type="hidden" name="seg" value={segment} />
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><rect x="4" y="5" width="16" height="15" rx="3" /><path d="M8 3v4M16 3v4M4 10h16" /></svg>
          <DateInput today={today} segment={segment} />
        </form>
      </nav>
      <nav className="segment" role="radiogroup" aria-label="Направление">
        {SEGMENTS.map((s) => (
          <a key={s.id} role="radio" aria-checked={segment === s.id} href={href(day, s.id)} aria-current={segment === s.id ? "true" : undefined}>{s.label}</a>
        ))}
      </nav>
    </div>
  );
}
