/** Текст приглашения (T-INVITE-SHARE) собирает API (поле share_text); здесь только работа с ним на клиенте. */

/** Делит текст и ссылку: если ссылка уже в тексте, из текста она убирается (иначе в чате будет дважды). */
export function splitShare(shareText: string, url: string): { text: string; url: string } {
  const text = shareText.split(url).join("").replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
  return { text, url };
}

/** Текст для буфера: с ссылкой в конце, ровно один раз. */
export function copyText(shareText: string, url: string): string {
  return shareText.includes(url) ? shareText : `${shareText}\n${url}`.trim();
}

/** Ссылка для «Поделиться»: обычный адрес приложения (url из API, а если его нет — web_url). */
export function shareLink(inv: { url?: string | null; web_url?: string | null }): string {
  return inv.web_url || inv.url || "";
}
