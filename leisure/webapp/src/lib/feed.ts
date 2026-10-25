// Лента рекомендаций (docs/PIVOT-PWA.md, версия 2): дни, направления, «успеваешь». Чистые функции, покрыты тестами.
import { dateShort, wdShort } from "./format";

export type DayKey = "today" | "tomorrow" | "day2" | "week" | `${number}-${number}-${number}`;
export type Segment = "leisure" | "business" | "all";

export const SEGMENTS: { id: Segment; label: string }[] = [
  { id: "leisure", label: "Досуг" },
  { id: "business", label: "Дело" },
  { id: "all", label: "Всё" },
];

const ISO = /^\d{4}-\d{2}-\d{2}$/;

export function parseDay(v: string | undefined): DayKey {
  if (v === "tomorrow" || v === "day2" || v === "week") return v;
  if (v && ISO.test(v)) return v as DayKey;
  return "today";
}
export const parseSegment = (v: string | undefined): Segment => (v === "business" || v === "all" ? v : "leisure");

/** Сдвиг даты на n дней (ISO → ISO), без часовых поясов. */
export function addDays(iso: string, n: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
}

/** Какие даты покрывает выбор: один день или семь дней начиная с сегодня. */
export function daysOf(key: DayKey, today: string): string[] {
  if (key === "today") return [today];
  if (key === "tomorrow") return [addDays(today, 1)];
  if (key === "day2") return [addDays(today, 2)];
  if (key === "week") return Array.from({ length: 7 }, (_, i) => addDays(today, i));
  return [key];
}

/** Значение date для GET /api/feed: today | tomorrow | week | YYYY-MM-DD. «Послезавтра» API не знает — шлём дату. */
export function apiDate(key: DayKey, today: string): string {
  if (key === "day2") return addDays(today, 2);
  return key;
}

/** Подписи DayStrip; выбранная календарём дата показывается как «Сб, 1 ноя». */
export function dayLabel(key: DayKey): string {
  if (key === "today") return "Сегодня";
  if (key === "tomorrow") return "Завтра";
  if (key === "day2") return "Послезавтра";
  if (key === "week") return "Неделя";
  const wd = wdShort(key);
  return `${wd.charAt(0).toUpperCase()}${wd.slice(1)}, ${dateShort(key)}`;
}

/** Строка времени на карточке (служебная роль): «СЕГОДНЯ · 19:00», «ЗАВТРА · 13:00–15:00», «СБ, 1 НОЯ · 12:00». */
export function timeLine(day: string, today: string, start: string | null, end: string | null): string {
  const diff = Math.round((Date.parse(day) - Date.parse(today)) / 86400_000);
  const d = diff === 0 ? "Сегодня" : diff === 1 ? "Завтра" : diff === 2 ? "Послезавтра" : dayLabel(day as DayKey);
  const t = start ? (end && end !== start ? `${start}–${end}` : start) : "";
  return t ? `${d} · ${t}` : d;
}

const mins = (t: string | null | undefined): number | null => (t && /^\d{1,2}:\d{2}$/.test(t) ? Number(t.split(":")[0]) * 60 + Number(t.split(":")[1]) : null);

/** «Успеваешь»: сегодня и старт не раньше, чем через время на дорогу (по умолчанию 40 мин). Без времени старта — не показываем. */
export function canMakeIt(day: string, start: string | null, nowMinutes: number, today: string, travelMinutes = 40): boolean {
  if (day !== today) return false;
  const s = mins(start);
  return s != null && s >= nowMinutes + travelMinutes;
}

/** Минуты с полуночи по Москве для «успеваешь». */
export function moscowNowMinutes(now = Date.now()): number {
  const d = new Date(now + 3 * 3600_000);
  return d.getUTCHours() * 60 + d.getUTCMinutes();
}

/** Бизнес-направления каталога (segment=business); остальное — досуг. */
export const isBusiness = (category: string, business: string[]) => business.includes(category);
