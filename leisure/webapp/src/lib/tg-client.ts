"use client";
// Тонкая обёртка над Telegram Mini App без SDK-скрипта (он замедляет заставку): если SDK всё же подключён, берём его методы,
// иначе шлём те же события напрямую (протокол web_app_* из документации Mini Apps).

type WebApp = {
  initData?: string;
  openTelegramLink?: (url: string) => void;
  requestWriteAccess?: (cb?: (granted: boolean) => void) => void;
};
const tgWin = () => window as unknown as { Telegram?: { WebApp?: WebApp }; TelegramWebviewProxy?: { postEvent: (t: string, d: string) => void } };

/** Есть ли initData: Mini App открыт в Telegram (или хранится с запуска в этой вкладке). */
export function inTelegram(): boolean {
  try {
    if (tgWin().Telegram?.WebApp?.initData) return true;
    if (new URLSearchParams(window.location.hash.replace(/^#/, "")).get("tgWebAppData")) return true;
    return !!sessionStorage.getItem("leisure:initData");
  } catch {
    return false;
  }
}

function postEvent(type: string, data: unknown): boolean {
  try {
    const w = tgWin();
    const json = JSON.stringify(data);
    if (w.TelegramWebviewProxy) {
      w.TelegramWebviewProxy.postEvent(type, json);
      return true;
    }
    if (window.parent !== window) {
      window.parent.postMessage(JSON.stringify({ eventType: type, eventData: data }), "https://web.telegram.org");
      return true;
    }
  } catch {}
  return false;
}

/** Открывает ссылку t.me внутри Telegram (выбор чата и т. п.). Возвращает false, если пришлось открыть как обычную ссылку. */
export function openTelegramLink(url: string): boolean {
  try {
    const wa = tgWin().Telegram?.WebApp;
    if (wa?.openTelegramLink) {
      wa.openTelegramLink(url);
      return true;
    }
  } catch {}
  const path = url.replace(/^https:\/\/t\.me/, "");
  if (inTelegram() && path !== url && postEvent("web_app_open_tg_link", { path_full: path })) return true;
  window.open(url, "_blank", "noopener,noreferrer");
  return false;
}

let sdk: Promise<WebApp | null> | null = null;
/** SDK подгружается только когда нужен ответ от Telegram (право писать): остальным страницам скрипт не нужен. */
function loadSdk(): Promise<WebApp | null> {
  const ready = tgWin().Telegram?.WebApp;
  if (ready) return Promise.resolve(ready);
  sdk ??= new Promise((resolve) => {
    const el = document.createElement("script");
    el.src = "https://telegram.org/js/telegram-web-app.js";
    el.async = true;
    el.onload = () => resolve(tgWin().Telegram?.WebApp ?? null);
    el.onerror = () => resolve(null);
    document.head.appendChild(el);
  });
  return sdk;
}

/** Диалог Telegram «разрешить писать» (Telegram.WebApp.requestWriteAccess); resolve(true), если право выдано. Отказ не ошибка. */
export async function requestWriteAccess(): Promise<boolean> {
  const wa = await loadSdk();
  if (!wa?.requestWriteAccess) return false;
  return new Promise((resolve) => {
    try {
      wa.requestWriteAccess!((granted) => resolve(!!granted));
    } catch {
      resolve(false);
    }
    setTimeout(() => resolve(false), 60_000);
  });
}
