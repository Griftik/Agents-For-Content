import "server-only";
import { headers } from "next/headers";
import { miniAppLink, writeChatLink } from "./invite-share";

export const apiBase = () => (process.env.API_BASE_URL || "http://localhost:8000").replace(/\/+$/, "");
export const apiKey = () => process.env.API_KEY || "";
// Ключ собирается динамически, чтобы Next не вшил значение при сборке: имя бота читается из окружения на старте.
const BOT_ENV = "NEXT_PUBLIC_BOT_USERNAME";
export const botUsername = () => (process.env[BOT_ENV] || "").replace(/^@/, "");

/** Публичный адрес веба: WEB_BASE_URL, иначе по заголовкам запроса. */
export async function webBaseUrl(): Promise<string> {
  if (process.env.WEB_BASE_URL) return process.env.WEB_BASE_URL.replace(/\/+$/, "");
  const h = await headers();
  const host = h.get("x-forwarded-host") || h.get("host") || "localhost:3000";
  const proto = h.get("x-forwarded-proto") || (host.startsWith("localhost") ? "http" : "https");
  return `${proto}://${host}`;
}

// Короткое имя Mini App в BotFather (t.me/<бот>/<app>): читается на старте так же, как имя бота.
const APP_ENV = "NEXT_PUBLIC_MINIAPP_SHORT_NAME";
export const miniAppShortName = () => (process.env[APP_ENV] || "").replace(/^\/+|\/+$/g, "");

/** Ссылка на Mini App с start_param: `t.me/<бот>/<app>?startapp=inv_<код>`; null, если бот не задан. */
export const miniLink = (kind: "inv" | "ref", code: string): string | null => miniAppLink(botUsername(), miniAppShortName(), kind, code);

/** Запасная ссылка «Открыть чат с ботом» (?start=w_<код>), если Telegram не дал право писать. */
export const chatLink = (code?: string | null): string | null => writeChatLink(botUsername(), code);

export function botLink(start?: string): string | null {
  const bot = botUsername();
  if (!bot) return null;
  return `https://t.me/${bot}${start ? `?start=${encodeURIComponent(start)}` : ""}`;
}
