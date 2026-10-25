import { describe, expect, it } from "vitest";
import type { Decision, EventT, PlanItem } from "./api-types";
import { hasUnmarkedDecisions, hasUnmarkedPast, pastItems } from "./plan";

const ev = { slug: "x", title: "x", dates: [] } as unknown as EventT;
const pi = (slug: string, status: string, day: string): PlanItem => ({ event: { ...ev, slug }, status, day, conflict: false, links: { gcal: "", outlook: "", ics: "", tg: "", page: "" } });
const d = (slug: string, status: string, day: string): Decision => ({ event_id: null, event_slug: slug, status, reason: null, day, rating: null });

describe("план: прошедшие события", () => {
  it("точка на вкладке, пока в past есть «иду» без отметки", () => {
    expect(hasUnmarkedPast([pi("a", "иду", "2026-10-23")])).toBe(true);
    expect(hasUnmarkedPast([pi("a", "сходил", "2026-10-23"), pi("b", "не сходил", "2026-10-22")])).toBe(false);
    expect(hasUnmarkedPast(undefined)).toBe(false);
  });
  it("неотмеченные первыми, затем отмеченные, свежие выше", () => {
    const list = pastItems([pi("a", "сходил", "2026-10-20"), pi("b", "иду", "2026-10-18"), pi("c", "не сходил", "2026-10-24")]);
    expect(list.map((x) => x.event.slug)).toEqual(["b", "c", "a"]);
  });
  it("по решениям: «иду» с датой до сегодня", () => {
    expect(hasUnmarkedDecisions([d("a", "иду", "2026-10-23")], "2026-10-25")).toBe(true);
    expect(hasUnmarkedDecisions([d("a", "иду", "2026-10-25")], "2026-10-25")).toBe(false);
  });
});
