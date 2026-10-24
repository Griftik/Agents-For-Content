/** Текст приглашения (T-INVITE-SHARE) собирает API (поле share_text); здесь только работа с ним на клиенте. */

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

/**
 * Запасной путь к праву писать: чат с ботом по `?start=w_<код приглашения>` (бэкенд на /start w_ ставит can_write и отвечает коротко).
 * Без кода — просто чат с ботом. null, если имя бота не задано.
 */
export function writeChatLink(bot: string, code?: string | null): string | null {
  if (!bot) return null;
  return code && /^[A-Za-z0-9]{4,32}$/.test(code) ? `https://t.me/${bot}?start=w_${code}` : `https://t.me/${bot}`;
}
