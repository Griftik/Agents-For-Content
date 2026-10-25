import { describe, expect, it } from "vitest";
import { MAX_TAPS_TO_GOING, inviteeTaps, needsConsent } from "./invite";

describe("нажатия приглашённого до записанного «иду»", () => {
  it("согласия нет: ссылка, галочка, «Иду вместе» = 3", () => {
    const t = inviteeTaps({ hasConsent: false });
    expect(t).toEqual(["link", "consent", "accept"]);
    expect(t.length).toBeLessThanOrEqual(MAX_TAPS_TO_GOING);
  });
  it("согласие уже есть: ссылка и «Иду вместе» = 2", () => {
    expect(inviteeTaps({ hasConsent: true })).toEqual(["link", "accept"]);
  });
  it("галочка нужна, пока нет согласия", () => {
    expect(needsConsent({ hasConsent: false })).toBe(true);
    expect(needsConsent({ hasConsent: true })).toBe(false);
  });
  it("браузер и установленное приложение идут одним путём: отдельного шага входа нет", () => {
    expect(inviteeTaps({ hasConsent: false })).not.toContain("open-in-telegram");
  });
});
