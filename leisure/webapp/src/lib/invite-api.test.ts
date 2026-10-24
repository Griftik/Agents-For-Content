import { describe, expect, it } from "vitest";
import { toInviteAccepted, toInviteCreated, toInviteView } from "./invite-api";

const ctx = { event: { title: "Т", venue: "П", why_fit_hint: "", start_time: "13:00", end_time: null }, day: "2026-10-24", bot: "dosug_bot", app: "app" };

describe("адаптер ответов приглашений", () => {
  it("контракт §6: status и inviter_name null", () => {
    const v = toInviteView({ event: { slug: "a" }, day: "2026-10-24", inviter_name: null, status: "unpublished", accepted: 2 });
    expect(v).toMatchObject({ status: "unpublished", inviter_name: null, accepted: 2, day: "2026-10-24" });
  });
  it("текущая схема бэкенда: state → status", () => {
    expect(toInviteView({ state: "ok" }).status).toBe("active");
    expect(toInviteView({ state: "event_gone" }).status).toBe("unpublished");
    expect(toInviteView({ state: "past" }).status).toBe("past");
  });
  it("создание: ссылка startapp сохраняется, ?start= заменяется на Mini App, share_text достраивается", () => {
    const ok = toInviteCreated({ code: "ABCD1234", url: "https://t.me/b/app?startapp=inv_ABCD1234", web_url: "w", share_text: "текст" }, ctx);
    expect(ok).toEqual({ code: "ABCD1234", url: "https://t.me/b/app?startapp=inv_ABCD1234", web_url: "w", share_text: "текст" });
    const old = toInviteCreated({ code: "ABCD1234", bot_link: "https://t.me/b?start=inv_ABCD1234", web_link: "/e/a?inv=ABCD1234" }, ctx);
    expect(old.url).toBe("https://t.me/dosug_bot/app?startapp=inv_ABCD1234");
    expect(old.web_url).toBe("/e/a?inv=ABCD1234");
    expect(old.share_text).toContain(old.url);
  });
  it("принятие: together_with или companions, profile_state или запасное значение", () => {
    expect(toInviteAccepted({ decision: {}, together_with: "Алина", profile_state: "onboarded" }, "new")).toMatchObject({ together_with: "Алина", profile_state: "onboarded" });
    expect(toInviteAccepted({ decision: {}, companions: ["Алина"] }, "onboarded")).toMatchObject({ together_with: "Алина", profile_state: "onboarded" });
    expect(toInviteAccepted({ decision: {} }, "new")).toMatchObject({ together_with: null, profile_state: "new" });
  });
});
