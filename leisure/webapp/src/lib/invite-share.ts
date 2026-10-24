import type { EventT } from "./api-types";
import { dateShort, timeRange, wdFull } from "./format";

/** Текст приглашения от первого лица (T-INVITE-SHARE). Основной источник — поле share_text из API; здесь запасной сбор и мок. */

const clip = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1).trimEnd()}…` : s);
const firstSentence = (s: string) => (/^.*?[.!?](?=\s|$)/s.exec(s.trim())?.[0] ?? s).trim();

export function buildShareText(ev: Pick<EventT, "title" | "venue" | "why_fit_hint" | "start_time" | "end_time">, day: string | null, link: string): string {
  const title = ev.title.length > 60 ? `${ev.title.slice(0, 59)}…` : ev.title;
  const when = [day ? `${wdFull(day).toLowerCase()}, ${dateShort(day)}` : "", timeRange(ev as EventT), clip(ev.venue || "", 40)].filter(Boolean).join(", ");
  const hint = ev.why_fit_hint ? clip(firstSentence(ev.why_fit_hint), 70) : "";
  const head = `Иду на «${title}»${when ? `: ${when}` : ""}.${hint ? ` ${hint}` : ""}`;
  return `${head}\nПойдёшь со мной? ${link}`;
}

/** Делит текст и ссылку: если ссылка уже в тексте, из текста она убирается (иначе в чате будет дважды). */
export function splitShare(shareText: string, url: string): { text: string; url: string } {
  const text = shareText.split(url).join("").replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
  return { text, url };
}

/** Ссылка системного выбора чата в Telegram. */
export const tgShareLink = (url: string, text: string) =>
  `https://t.me/share/url?url=${encodeURIComponent(url)}&text=${encodeURIComponent(text)}`;

/** Текст для буфера: с ссылкой в конце, ровно один раз. */
export function copyText(shareText: string, url: string): string {
  return shareText.includes(url) ? shareText : `${shareText}\n${url}`.trim();
}

/** Ссылка на Mini App: t.me/<бот>/<app>?startapp=<вид>_<код>; без короткого имени приложения — на главное приложение бота. */
export function miniAppLink(bot: string, app: string, kind: "inv" | "ref", code: string): string | null {
  if (!bot) return null;
  const path = app ? `${bot}/${app}` : bot;
  return `https://t.me/${path}?startapp=${kind}_${encodeURIComponent(code)}`;
}
