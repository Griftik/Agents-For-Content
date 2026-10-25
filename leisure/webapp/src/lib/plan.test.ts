import { describe, expect, it } from "vitest";
import type { Decision } from "./api-types";
import { hasUnmarkedPast, pastDecisions } from "./plan";

const d = (slug: string, status: string, day: string): Decision => ({ event_id: null, event_slug: slug, status, reason: null, day, rating: null });
const T = "2026-10-25";

describe("план: прошедшие события", () => {
  it("точка на вкладке, пока есть «иду» в прошлом без отметки", () => {
    expect(hasUnmarkedPast([d("a", "иду", "2026-10-23")], T)).toBe(true);
    expect(hasUnmarkedPast([d("a", "сходил", "2026-10-23"), d("b", "иду", "2026-10-26")], T)).toBe(false);
    expect(hasUnmarkedPast([d("a", "иду", T)], T)).toBe(false);
  });
  it("неотмеченные первыми, затем отмеченные, свежие выше", () => {
    const list = pastDecisions([d("a", "сходил", "2026-10-20"), d("b", "иду", "2026-10-18"), d("c", "не сходил", "2026-10-24"), d("x", "мимо", "2026-10-19")], T);
    expect(list.map((x) => x.event_slug)).toEqual(["b", "c", "a"]);
  });
});
