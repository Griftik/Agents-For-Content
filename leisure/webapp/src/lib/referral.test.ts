import { describe, expect, it } from "vitest";
import { REF_ASK_DAYS, canAskReferral } from "./referral";

const NOW = new Date(2026, 9, 25, 15, 0).getTime();

describe("момент рекомендации", () => {
  it("только после 4–5", () => {
    expect(canAskReferral(5, null, NOW)).toBe(true);
    expect(canAskReferral(4, null, NOW)).toBe(true);
    expect(canAskReferral(3, null, NOW)).toBe(false);
    expect(canAskReferral(1, null, NOW)).toBe(false);
  });
  it("не чаще раза в две недели", () => {
    expect(canAskReferral(5, NOW - 86400_000, NOW)).toBe(false);
    expect(canAskReferral(5, NOW - (REF_ASK_DAYS - 1) * 86400_000, NOW)).toBe(false);
    expect(canAskReferral(5, NOW - REF_ASK_DAYS * 86400_000, NOW)).toBe(true);
  });
});
