import "server-only";
import { headers } from "next/headers";

export const apiBase = () => (process.env.API_BASE_URL || "http://localhost:8000").replace(/\/+$/, "");
export const apiKey = () => process.env.API_KEY || "";

/** Публичный адрес веба: WEB_BASE_URL, иначе по заголовкам запроса. */
export async function webBaseUrl(): Promise<string> {
  if (process.env.WEB_BASE_URL) return process.env.WEB_BASE_URL.replace(/\/+$/, "");
  const h = await headers();
  const host = h.get("x-forwarded-host") || h.get("host") || "localhost:3000";
  const proto = h.get("x-forwarded-proto") || (host.startsWith("localhost") ? "http" : "https");
  return `${proto}://${host}`;
}
