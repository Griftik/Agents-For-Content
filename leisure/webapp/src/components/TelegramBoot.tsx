"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

const KEY = "leisure:initData";
const SCHEME = "leisure:scheme";

function readInitData(): string {
  try {
    const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const fromHash = hash.get("tgWebAppData");
    if (fromHash) {
      sessionStorage.setItem(KEY, fromHash);
      const theme = hash.get("tgWebAppThemeParams");
      if (theme) {
        const bg = (JSON.parse(theme) as { bg_color?: string }).bg_color;
        if (bg) sessionStorage.setItem(SCHEME, luminance(bg) < 0.45 ? "dark" : "light");
      }
      return fromHash;
    }
  } catch {}
  try {
    const w = window as unknown as { Telegram?: { WebApp?: { initData?: string; colorScheme?: string } } };
    if (w.Telegram?.WebApp?.initData) return w.Telegram.WebApp.initData;
    return sessionStorage.getItem(KEY) ?? "";
  } catch {
    return "";
  }
}

function luminance(hex: string): number {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex);
  if (!m) return 1;
  const n = parseInt(m[1], 16);
  return (0.2126 * ((n >> 16) & 255) + 0.7152 * ((n >> 8) & 255) + 0.0722 * (n & 255)) / 255;
}

/** Сообщает Telegram, что страница готова (без SDK-скрипта): иначе заставка Mini App висит дольше. */
function tellTelegram() {
  const msg = (type: string) => {
    try {
      const w = window as unknown as { TelegramWebviewProxy?: { postEvent: (t: string, d: string) => void } };
      if (w.TelegramWebviewProxy) w.TelegramWebviewProxy.postEvent(type, "{}");
      else if (window.parent !== window) window.parent.postMessage(JSON.stringify({ eventType: type, eventData: {} }), "https://web.telegram.org");
    } catch {}
  };
  msg("web_app_ready");
  msg("web_app_expand");
}

/**
 * Клиентский слой Mini App: берёт initData из Telegram, меняет его на cookie сессии через /api/auth/telegram
 * (подпись проверяет сервер) и подхватывает светлую/тёмную тему. Страницы читаются и без него, если сессия уже есть.
 */
export function TelegramBoot({ authed }: { authed: boolean }) {
  const router = useRouter();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const initData = readInitData();
    if (initData) tellTelegram();
    try {
      const scheme = sessionStorage.getItem(SCHEME);
      if (scheme) document.documentElement.dataset.theme = scheme;
    } catch {}
    if (authed || !initData) return;
    fetch("/api/auth/telegram", { method: "POST", headers: { "X-Telegram-Init-Data": initData }, credentials: "same-origin" })
      .then((r) => {
        if (r.ok) router.refresh();
        else setFailed(true);
      })
      .catch(() => setFailed(true));
  }, [authed, router]);

  if (!failed) return null;
  return (
    <p role="alert" className="notice warn" style={{ margin: "12px auto", maxWidth: 720 }}>
      Не получилось войти через Telegram: данные устарели. Закрой приложение и открой его из бота заново.
    </p>
  );
}
