import "server-only";
import { headers } from "next/headers";

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

export function botLink(start?: string): string | null {
  const bot = botUsername();
  if (!bot) return null;
  return `https://t.me/${bot}${start ? `?start=${encodeURIComponent(start)}` : ""}`;
}
