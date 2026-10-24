"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { findStartParam, inviteHref, parseStartParam } from "@/lib/start-param";

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

function readStartParam(initData: string): string | null {
  let unsafe: string | undefined;
  try {
    const w = window as unknown as { Telegram?: { WebApp?: { initDataUnsafe?: { start_param?: string } } } };
    unsafe = w.Telegram?.WebApp?.initDataUnsafe?.start_param;
  } catch {}
  return findStartParam({ initData, unsafe, hash: window.location.hash, search: window.location.search });
}

async function exchange(initData: string): Promise<boolean> {
  try {
    const r = await fetch("/api/auth/telegram", { method: "POST", headers: { "X-Telegram-Init-Data": initData }, credentials: "same-origin" });
    return r.ok;
  } catch {
    return false;
  }
}

/**
 * Клиентский слой Mini App: берёт initData из Telegram, меняет его на cookie сессии через /api/auth/telegram
 * (подпись проверяет сервер), подхватывает светлую/тёмную тему и разбирает start_param:
 * `inv_<код>` открывает /e/<слаг>?inv=<код> (слаг даёт GET /api/invites/{код}), `ref_<код>` кладёт код в cookie и ведёт
 * на приветствие онбординга. Каждый start_param обрабатывается один раз за вкладку, иначе любая перезагрузка возвращала бы на приглашение.
 * Страницы читаются и без этого слоя, если сессия уже есть.
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

    const raw = readStartParam(initData);
    const sp = parseStartParam(raw);
    let handled = true;
    if (sp && raw) {
      try {
        handled = sessionStorage.getItem(`leisure:sp:${raw}`) === "1";
        if (!handled) sessionStorage.setItem(`leisure:sp:${raw}`, "1");
      } catch {
        handled = false;
      }
    }
    const route = sp && !handled ? sp : null;

    (async () => {
      let ok = authed;
      if (!authed && initData) {
        ok = await exchange(initData);
        if (!ok) setFailed(true);
      }
      if (route?.kind === "inv") {
        let slug = "-"; // несуществующий слаг: страница сама покажет «Эта ссылка не работает» по коду
        try {
          const r = await fetch(`/api/invite/${encodeURIComponent(route.code)}`, { credentials: "same-origin" });
          const j = (await r.json()) as { slug?: string | null };
          if (r.ok && j.slug) slug = j.slug;
        } catch {}
        router.replace(inviteHref(slug, route.code));
      } else if (route?.kind === "ref") {
        try {
          await fetch("/api/ref", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code: route.code }), credentials: "same-origin" });
        } catch {}
        router.replace("/profile?onboarding=welcome");
      } else if (!authed && ok) {
        router.refresh();
      }
    })();
  }, [authed, router]);

  if (!failed) return null;
  return (
    <p role="alert" className="notice warn" style={{ margin: "12px auto", maxWidth: 720 }}>
      Не получилось войти. Закрой приложение и открой его из Telegram ещё раз.
    </p>
  );
}
