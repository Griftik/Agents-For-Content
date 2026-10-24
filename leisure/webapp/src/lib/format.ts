import type { EventT } from "./api-types";

const WD_SHORT = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];
const WD_FULL = ["Воскресенье", "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"];
const WD_PREP = ["воскресенье", "понедельник", "вторник", "среду", "четверг", "пятницу", "субботу"];
const MONTH_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];
const MONTH_SHORT = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];

function parts(iso: string) {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  return { y, m: m - 1, d, wd: dt.getUTCDay() };
}

export const dayNum = (iso: string) => parts(iso).d;
export const wdShort = (iso: string) => WD_SHORT[parts(iso).wd];
export const wdFull = (iso: string) => WD_FULL[parts(iso).wd];
export const wdPrep = (iso: string) => WD_PREP[parts(iso).wd];
export const dateShort = (iso: string) => `${parts(iso).d} ${MONTH_SHORT[parts(iso).m]}`;
export const dateLong = (iso: string) => `${parts(iso).d} ${MONTH_GEN[parts(iso).m]}`;

/** Подпись под числом в карточке: дни выходных («сб–вс») или месяц для событий на горизонте. */
export function whenLabel(dates: string[], weekend: string[]): { num: string; sub: string } {
  const sorted = [...dates].sort();
  const inWeekend = sorted.filter((d) => weekend.includes(d));
  if (inWeekend.length) {
    const sub =
      inWeekend.length === 1
        ? wdShort(inWeekend[0])
        : inWeekend.length === 2
          ? `${wdShort(inWeekend[0])}–${wdShort(inWeekend[1])}`
          : inWeekend.map(wdShort).join(", ");
    return { num: String(dayNum(inWeekend[0])), sub };
  }
  const first = sorted.find((d) => d >= weekend[0]) ?? sorted[0];
  if (!first) return { num: "—", sub: "" };
  const more = sorted.filter((d) => d > first).length;
  return { num: String(dayNum(first)), sub: `${MONTH_SHORT[parts(first).m]}${more ? ` +${more}` : ""}` };
}

export const startTime = (ev: EventT) => ev.start_time || "";

export function priceLabel(ev: EventT): string {
  if (ev.free) return "бесплатно";
  if (ev.price_from != null) return `от ${ev.price_from.toLocaleString("ru-RU").replace(/ /g, " ")} ₽`;
  const t = (ev.price_text || "").trim();
  return t && t.length <= 40 ? t : "";
}

export function placeLine(ev: EventT): { venue: string; rest: string } {
  const rest = [ev.address, ev.metro ? `м. ${ev.metro}` : ""].filter(Boolean).join(" · ");
  return { venue: ev.venue, rest };
}

/** Событие целиком вне ближайших выходных — «на горизонте». */
export const isHorizon = (ev: EventT, weekend: string[]) => !ev.dates.some((d) => weekend.includes(d));

export function shareUrl(ev: EventT, day: string | null | undefined, base: string): string {
  const d = day || ev.dates[0] || "";
  const when = [d ? `${dateLong(d)}` : "", ev.time_text].filter(Boolean).join(", ");
  const where = [ev.venue, ev.address].filter(Boolean).join(", ");
  const text = [ev.title, when, where, ev.why_fit_hint].filter(Boolean).join("\n").slice(0, 700);
  return "https://t.me/share/url?" + new URLSearchParams({ url: `${base}/e/${ev.slug}`, text }).toString();
}

export const STATUS_LABEL: Record<string, string> = { иду: "Иду", может: "Может быть", интересно: "Интересно", мимо: "Мимо" };

/** Разбор ?today= (только для проверки в разработке). */
export function parseToday(v: string | undefined): string | undefined {
  return v && /^\d{4}-\d{2}-\d{2}$/.test(v) ? v : undefined;
}

export const first = (v: string | string[] | undefined): string | undefined => (Array.isArray(v) ? v[0] : v);
