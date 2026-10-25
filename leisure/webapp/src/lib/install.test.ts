import { describe, expect, it } from "vitest";
import { DISMISS_DAYS, detectPlatform, installHint, type InstallInput } from "./install";

const NOW = 1_800_000_000_000;
const base: InstallInput = { ios: false, iosSafari: false, standalone: false, hasPrompt: true, visits: 2, going: false, dismissedAt: null, dismissCount: 0, now: NOW };

const IOS_SAFARI = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1";
const IOS_CHROME = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/124.0.0.0 Mobile/15E148 Safari/604.1";
const ANDROID = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36";

describe("платформа", () => {
  it("iOS Safari, Chrome на iOS и Android различаются", () => {
    expect(detectPlatform(IOS_SAFARI)).toEqual({ ios: true, iosSafari: true });
    expect(detectPlatform(IOS_CHROME)).toEqual({ ios: true, iosSafari: false });
    expect(detectPlatform(ANDROID)).toEqual({ ios: false, iosSafari: false });
  });
  it("iPadOS под видом Mac определяется по касаниям", () => {
    expect(detectPlatform("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.4 Safari/605.1.15", 5)).toEqual({ ios: true, iosSafari: true });
    expect(detectPlatform("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.4 Safari/605.1.15", 0).ios).toBe(false);
  });
});

describe("баннер «Установить на экран»", () => {
  it("не на первом визите, но после второго или после первого «иду»", () => {
    expect(installHint({ ...base, visits: 1 })).toBe("none");
    expect(installHint({ ...base, visits: 2 })).toBe("prompt");
    expect(installHint({ ...base, visits: 1, going: true })).toBe("prompt");
  });
  it("в установленном приложении не показывается", () => {
    expect(installHint({ ...base, standalone: true })).toBe("none");
  });
  it("без beforeinstallprompt на Android и десктопе молчит", () => {
    expect(installHint({ ...base, hasPrompt: false })).toBe("none");
  });
  it("iOS Safari: пошаговая подсказка через «Поделиться»; другие браузеры iOS: открыть в Safari", () => {
    expect(installHint({ ...base, ios: true, iosSafari: true, hasPrompt: false })).toBe("ios-steps");
    expect(installHint({ ...base, ios: true, iosSafari: false, hasPrompt: false })).toBe("ios-open-safari");
  });
  it("после «Не сейчас» молчит две недели, после третьего отказа насовсем", () => {
    const d = NOW - 86400_000;
    expect(installHint({ ...base, dismissedAt: d, dismissCount: 1 })).toBe("none");
    expect(installHint({ ...base, dismissedAt: NOW - (DISMISS_DAYS + 1) * 86400_000, dismissCount: 1 })).toBe("prompt");
    expect(installHint({ ...base, dismissedAt: NOW - 100 * 86400_000, dismissCount: 3 })).toBe("none");
  });
});
