"use client";

import { useEffect, useState } from "react";
import { detectPlatform, installHint, type InstallHint } from "@/lib/install";

const K = { visits: "leisure:visits", going: "leisure:going", dismissedAt: "leisure:install:dismissedAt", dismissCount: "leisure:install:dismissCount" };

type DeferredPrompt = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: string }> };

const num = (k: string): number => {
  try {
    return Number(localStorage.getItem(k)) || 0;
  } catch {
    return 0;
  }
};
const put = (k: string, v: string) => {
  try {
    localStorage.setItem(k, v);
  } catch {}
};

/**
 * PWA: регистрирует service worker и показывает мягкий баннер «Установить на экран» (правила — lib/install.ts).
 * Счётчик визитов и признак «уже нажимал Иду» хранятся в браузере: это удобство одного устройства, терять их не страшно.
 */
export function PwaBoot() {
  const [hint, setHint] = useState<InstallHint>("none");
  const [prompt, setPrompt] = useState<DeferredPrompt | null>(null);

  useEffect(() => {
    if ("serviceWorker" in navigator && (window.isSecureContext || location.hostname === "localhost")) {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {});
    }
    // визит считаем один раз за сессию вкладки
    try {
      if (!sessionStorage.getItem("leisure:visit-counted")) {
        sessionStorage.setItem("leisure:visit-counted", "1");
        put(K.visits, String(num(K.visits) + 1));
      }
    } catch {}

    const evaluate = (p: DeferredPrompt | null) => {
      const standalone = window.matchMedia("(display-mode: standalone)").matches || (navigator as unknown as { standalone?: boolean }).standalone === true;
      setHint(
        installHint({
          ...detectPlatform(navigator.userAgent, navigator.maxTouchPoints),
          standalone,
          hasPrompt: p != null,
          visits: num(K.visits),
          going: num(K.going) > 0,
          dismissedAt: num(K.dismissedAt) || null,
          dismissCount: num(K.dismissCount),
          now: Date.now(),
        }),
      );
    };
    evaluate(null);

    const onPrompt = (e: Event) => {
      e.preventDefault();
      setPrompt(e as DeferredPrompt);
      evaluate(e as DeferredPrompt);
    };
    // первое «Иду» (кнопка решения в форме): после него баннер уместен, даже если визит один
    const onSubmit = (e: Event) => {
      const b = (e as SubmitEvent).submitter as HTMLButtonElement | null;
      if (b?.name === "status" && b.value === "иду") {
        put(K.going, "1");
        evaluate(null);
      }
    };
    window.addEventListener("beforeinstallprompt", onPrompt);
    window.addEventListener("appinstalled", () => setHint("none"));
    document.addEventListener("submit", onSubmit, true);
    return () => {
      window.removeEventListener("beforeinstallprompt", onPrompt);
      document.removeEventListener("submit", onSubmit, true);
    };
  }, []);

  const dismiss = () => {
    put(K.dismissedAt, String(Date.now()));
    put(K.dismissCount, String(num(K.dismissCount) + 1));
    setHint("none");
  };
  const install = async () => {
    if (!prompt) return;
    await prompt.prompt();
    await prompt.userChoice.catch(() => null);
    setPrompt(null);
    setHint("none");
  };

  if (hint === "none") return null;
  return (
    <section className="install-bar card" role="region" aria-label="Установка на экран">
      <div className="stack" style={{ gap: 6 }}>
        <b>Установить на экран</b>
        {hint === "prompt" ? <p className="muted">Catch откроется в один тап, как обычное приложение.</p> : null}
        {hint === "ios-steps" ? (
          <ol className="muted" style={{ margin: 0, paddingLeft: 20 }}>
            <li>Нажми «Поделиться» (квадрат со стрелкой) внизу экрана Safari.</li>
            <li>Выбери «На экран „Домой“».</li>
            <li>Нажми «Добавить».</li>
          </ol>
        ) : null}
        {hint === "ios-open-safari" ? <p className="muted">На iPhone установить можно только из Safari: открой эту страницу в Safari и нажми «Поделиться» → «На экран „Домой“».</p> : null}
      </div>
      <div className="row">
        {hint === "prompt" ? <button type="button" className="btn primary" style={{ minHeight: 44 }} onClick={install}>Установить</button> : null}
        <button type="button" className="btn" style={{ minHeight: 44 }} onClick={dismiss}>Не сейчас</button>
      </div>
    </section>
  );
}
