import { describe, expect, it } from "vitest";
import { MAX_TAPS_TO_GOING, inviteeTaps, needsConsent } from "./invite";

describe("нажатия приглашённого до записанного «иду»", () => {
  it("Mini App, согласия нет: ссылка, галочка, «Иду вместе» = 3", () => {
    const t = inviteeTaps({ inTelegram: true, hasProfile: false });
    expect(t).toEqual(["link", "consent", "accept"]);
    expect(t.length).toBe(3);
    expect(t.length).toBeLessThanOrEqual(MAX_TAPS_TO_GOING);
  });
  it("Mini App, профиль уже есть: ссылка и «Иду вместе» = 2", () => {
    expect(inviteeTaps({ inTelegram: true, hasProfile: true })).toEqual(["link", "accept"]);
  });
  it("браузер без Telegram: добавляется «Открыть в Telegram» = 4 (запасной путь)", () => {
    const t = inviteeTaps({ inTelegram: false, hasProfile: false });
    expect(t).toEqual(["link", "open-in-telegram", "consent", "accept"]);
    expect(t.length).toBe(4);
  });
  it("галочка нужна, пока нет профиля", () => {
    expect(needsConsent({ hasProfile: false })).toBe(true);
    expect(needsConsent({ hasProfile: true })).toBe(false);
  });
  it("на основном пути (Telegram) предел в три нажатия выдержан при любом состоянии", () => {
    for (const hasProfile of [true, false]) {
      expect(inviteeTaps({ inTelegram: true, hasProfile }).length).toBeLessThanOrEqual(MAX_TAPS_TO_GOING);
    }
  });
});
