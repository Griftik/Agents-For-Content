// Мягкий баннер «Установить на экран» (docs/PIVOT-PWA.md §4): не на первом экране, а после второго визита или первого «иду»;
// не в установленном приложении; после «Не сейчас» молчим две недели, после третьего отказа больше не просим.

export const VISITS_BEFORE_OFFER = 2;
export const DISMISS_DAYS = 14;
export const MAX_DISMISSALS = 3;

export type Platform = { ios: boolean; iosSafari: boolean };

/** iOS Safari ставит на экран только через «Поделиться»; Chrome, Firefox и др. на iOS этого не умеют (нужен Safari). */
export function detectPlatform(ua: string, maxTouchPoints = 0): Platform {
  const iPadOs = /Macintosh/.test(ua) && maxTouchPoints > 1; // iPadOS 13+ выдаёт себя за Mac
  const ios = /iPhone|iPad|iPod/.test(ua) || iPadOs;
  const other = /CriOS|FxiOS|EdgiOS|OPiOS|GSA\//.test(ua);
  return { ios, iosSafari: ios && /Safari/.test(ua) && !other };
}

export type InstallInput = Platform & {
  /** Приложение уже запущено с экрана (display-mode: standalone, navigator.standalone). */
  standalone: boolean;
  /** Браузер дал событие beforeinstallprompt (Chrome, Edge, Android). */
  hasPrompt: boolean;
  visits: number;
  /** Человек уже нажимал «Иду». */
  going: boolean;
  dismissedAt: number | null;
  dismissCount: number;
  now: number;
};

export type InstallHint = "none" | "prompt" | "ios-steps" | "ios-open-safari";

export function installHint(s: InstallInput): InstallHint {
  if (s.standalone) return "none";
  if (s.visits < VISITS_BEFORE_OFFER && !s.going) return "none";
  if (s.dismissCount >= MAX_DISMISSALS) return "none";
  if (s.dismissedAt != null && s.now - s.dismissedAt < DISMISS_DAYS * 86400_000) return "none";
  if (s.ios) return s.iosSafari ? "ios-steps" : "ios-open-safari";
  return s.hasPrompt ? "prompt" : "none";
}
