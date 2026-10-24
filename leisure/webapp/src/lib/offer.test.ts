import { describe, expect, it } from "vitest";
import { offerAgain } from "./offer";

describe("повтор предложения подборки", () => {
  const p = { onboarded: false, offer_due: "2026-10-25", offer_seen: 1 };
  it("не раньше offer_due", () => {
    expect(offerAgain(p, "2026-10-24")).toBe(false);
    expect(offerAgain(p, "2026-10-25")).toBe(true);
    expect(offerAgain(p, "2026-11-01")).toBe(true);
  });
  it("один раз: после показа или «Не нужно» (offer_seen = 2) больше нет", () => {
    expect(offerAgain({ ...p, offer_seen: 2 }, "2026-10-26")).toBe(false);
  });
  it("не показывается без срока и тем, кто уже прошёл онбординг", () => {
    expect(offerAgain({ ...p, offer_due: null }, "2026-10-26")).toBe(false);
    expect(offerAgain({ ...p, onboarded: true }, "2026-10-26")).toBe(false);
  });
});
