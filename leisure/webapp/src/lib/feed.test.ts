import { describe, expect, it } from "vitest";
import { addDays, apiDate, canMakeIt, dayLabel, daysOf, parseDay, parseSegment, timeLine } from "./feed";

const T = "2026-10-25";

describe("лента: дни и направления", () => {
  it("разбирает выбор дня, по умолчанию сегодня", () => {
    expect(parseDay(undefined)).toBe("today");
    expect(parseDay("week")).toBe("week");
    expect(parseDay("2026-11-01")).toBe("2026-11-01");
    expect(parseDay("вчера")).toBe("today");
    expect(parseSegment(undefined)).toBe("leisure");
    expect(parseSegment("business")).toBe("business");
  });
  it("даты выбора: один день или неделя от сегодня", () => {
    expect(daysOf("today", T)).toEqual([T]);
    expect(daysOf("tomorrow", T)).toEqual(["2026-10-26"]);
    expect(daysOf("day2", T)).toEqual(["2026-10-27"]);
    expect(daysOf("week", T)).toHaveLength(7);
    expect(daysOf("week", T)[6]).toBe("2026-10-31");
    expect(addDays("2026-10-31", 1)).toBe("2026-11-01");
  });
  it("послезавтра уходит в API датой", () => {
    expect(apiDate("day2", T)).toBe("2026-10-27");
    expect(apiDate("today", T)).toBe("today");
  });
  it("подписи дней", () => {
    expect(dayLabel("today")).toBe("Сегодня");
    expect(dayLabel("2026-11-01")).toBe("Вс, 1 ноя");
    expect(timeLine(T, T, "19:00", null)).toBe("Сегодня · 19:00");
    expect(timeLine("2026-10-26", T, "13:00", "15:00")).toBe("Завтра · 13:00–15:00");
    expect(timeLine("2026-10-31", T, null, null)).toBe("Сб, 31 окт");
  });
});

describe("«успеваешь»", () => {
  it("только сегодня и не раньше, чем через время на дорогу", () => {
    const now = 17 * 60; // 17:00
    expect(canMakeIt(T, "19:00", now, T)).toBe(true);
    expect(canMakeIt(T, "17:30", now, T)).toBe(false);
    expect(canMakeIt(T, "17:40", now, T)).toBe(true);
    expect(canMakeIt(T, "19:00", now, T, 180)).toBe(false);
    expect(canMakeIt("2026-10-26", "19:00", now, T)).toBe(false);
    expect(canMakeIt(T, null, now, T)).toBe(false);
  });
});
