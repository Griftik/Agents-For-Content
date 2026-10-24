import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MockError, mockCall, mockEnabled, resetMock } from "./mock";

beforeEach(() => resetMock());
afterEach(() => vi.unstubAllEnvs());

describe("мок-режим MOCK_INVITES", () => {
  it("включается только флагом и только вне production", () => {
    vi.stubEnv("MOCK_INVITES", "");
    expect(mockEnabled()).toBe(false);
    vi.stubEnv("MOCK_INVITES", "1");
    vi.stubEnv("NODE_ENV", "test");
    expect(mockEnabled()).toBe(true);
    vi.stubEnv("NODE_ENV", "development");
    expect(mockEnabled()).toBe(true);
    vi.stubEnv("NODE_ENV", "production");
    expect(mockEnabled()).toBe(false);
  });

  it("GET приглашения: имя, скрытое имя и статусы", () => {
    const ok = mockCall("/api/invites/MOCKOK01") as { inviter_name: string; status: string; event_slug: string; event: { event: { slug: string } } };
    expect(ok).toMatchObject({ inviter_name: "Алина", status: "active", event_slug: "karmannyj-ongon", event: { event: { slug: "karmannyj-ongon" } } });
    expect(mockCall("/api/invites/MOCKGONE")).toMatchObject({ status: "gone", inviter_name: null });
    // совпадение и причины — только для друга с настроенным профилем
    expect(mockCall("/api/invites/MOCKOK01?user_id=1001")).toMatchObject({ score: 84, why: [{ t: "Творчество" }, { t: "Руками" }] });
    expect(mockCall("/api/invites/MOCKOK01?user_id=1002")).toMatchObject({ score: null, why: null });
    expect((mockCall("/api/invites/MOCKOK01?user_id=9001") as { is_own: boolean }).is_own).toBe(true);
    expect((mockCall("/api/invites/MOCKANON") as { inviter_name: null }).inviter_name).toBeNull();
    expect((mockCall("/api/invites/MOCKPAST") as { status: string }).status).toBe("past");
    expect((mockCall("/api/invites/MOCKUNPB") as { status: string }).status).toBe("unpublished");
    expect(() => mockCall("/api/invites/NOPE0000")).toThrow(MockError);
  });

  it("принятие без профиля требует согласия, с согласием создаёт профиль и решение", () => {
    const post = (body: object) => ({ method: "POST", body: JSON.stringify(body) });
    expect(() => mockCall("/api/invites/MOCKOK01/accept", post({ user_id: 5001, status: "going", consent: false }))).toThrowError(/consent_required/);
    const r = mockCall("/api/invites/MOCKOK01/accept", post({ user_id: 5001, status: "going", consent: true })) as {
      decision: { status: string }; together_with: string; profile_state: string;
    };
    expect(r).toMatchObject({ decision: { status: "иду" }, together_with: "Алина", profile_state: "new" });
    expect(() => mockCall("/api/profile/5001")).not.toThrow();
    // «иду» поставило повтор предложения на день события + 1, а согласие записано
    expect(mockCall("/api/profile/5001")).toMatchObject({ has_consent: true, offer_due: "2026-10-25" });
    // повторное принятие уже без галочки
    expect(() => mockCall("/api/invites/MOCKOK01/accept", post({ user_id: 5001, status: "maybe", consent: false }))).not.toThrow();
    // в план попало событие со ссылками календарей и подписью «вдвоём»
    const plan = mockCall("/api/plan/5001") as { days: Record<string, unknown[]> };
    expect(Object.values(plan.days).flat()).toHaveLength(1);
  });

  it("«Другие выходные под меня»: declined без согласия и без решения", () => {
    const r = mockCall("/api/invites/MOCKOK01/accept", { method: "POST", body: JSON.stringify({ user_id: 5003, status: "declined", consent: false }) }) as { decision: null };
    expect(r.decision).toBeNull();
  });

  it("прошедшее и снятое событие отвечают 410", () => {
    const post = { method: "POST", body: JSON.stringify({ user_id: 1001, status: "going", consent: false }) };
    expect(() => mockCall("/api/invites/MOCKPAST/accept", post)).toThrowError(/past/);
    expect(() => mockCall("/api/invites/MOCKUNPB/accept", post)).toThrowError(/unpublished/);
  });

  it("создание приглашения возвращает код, ссылку startapp и текст", () => {
    const r = mockCall("/api/invites", { method: "POST", body: JSON.stringify({ user_id: 1001, event_slug: "karmannyj-ongon", day: "2026-10-24" }) }) as { code: string; url: string; share_text: string };
    expect(r.url).toContain(`startapp=inv_${r.code}`);
    expect(r.share_text).toContain(r.url);
  });
});
