import { beforeEach, describe, expect, it, vi } from "vitest";
import { SESSION_COOKIE } from "@/lib/session-consts";
import { issueSession } from "@/lib/session-token";
import { resetMock } from "@/lib/mock";

// Серверные действия приглашений целиком, поверх мок-API: настоящая сессия (подписанный cookie), мок вместо бэкенда.
const jar = new Map<string, string>();
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (k: string) => (jar.has(k) ? { name: k, value: jar.get(k)! } : undefined),
    set: (k: string, v: string) => void jar.set(k, v),
  }),
  headers: async () => new Headers(),
}));
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));
vi.mock("next/navigation", () => ({
  redirect: (to: string) => {
    throw new Error(`REDIRECT:${to}`);
  },
}));

const SECRET = "test-secret";
const login = (uid: number) => jar.set(SESSION_COOKIE, issueSession(uid, SECRET).token);
const form = (o: Record<string, string>) => Object.entries(o).reduce((f, [k, v]) => (f.set(k, v), f), new FormData());

beforeEach(() => {
  vi.stubEnv("MOCK_INVITES", "1");
  vi.stubEnv("SESSION_SECRET", SECRET);
  vi.stubEnv("NEXT_PUBLIC_BOT_USERNAME", "dosug_bot");
  vi.stubEnv("NEXT_PUBLIC_MINIAPP_SHORT_NAME", "app");
  jar.clear();
  resetMock();
});

const actions = () => import("./actions");
const base = { code: "MOCKOK01", slug: "karmannyj-ongon", day: "2026-10-24" };

describe("acceptInviteAction", () => {
  it("без сессии — ошибка входа", async () => {
    const { acceptInviteAction } = await actions();
    const r = await acceptInviteAction({ phase: "idle" }, form({ ...base, status: "going" }));
    expect(r).toMatchObject({ phase: "error", error: "no-session" });
  });

  it("без согласия не ходит в API и просит галочку", async () => {
    login(5001);
    const { acceptInviteAction } = await actions();
    const r = await acceptInviteAction({ phase: "idle" }, form({ ...base, status: "going", needs_consent: "1" }));
    expect(r).toMatchObject({ phase: "error", error: "consent" });
  });

  it("с согласием записывает «иду», отдаёт имя, календари и предложение подборки", async () => {
    login(5001);
    const { acceptInviteAction } = await actions();
    const r = await acceptInviteAction({ phase: "idle" }, form({ ...base, status: "going", needs_consent: "1", consent: "on" }));
    expect(r.phase).toBe("done");
    if (r.phase !== "done") return;
    expect(r).toMatchObject({ status: "going", togetherWith: "Алина", profileState: "new" });
    expect(r.links?.ics).toBe("/api/events/karmannyj-ongon/ics?day=2026-10-24");
    expect(r.links?.gcal).toContain("calendar.google.com");
  });

  it("у человека с профилем галочка не нужна, предложения подборки нет", async () => {
    login(1001);
    const { acceptInviteAction } = await actions();
    const r = await acceptInviteAction({ phase: "idle" }, form({ ...base, status: "maybe" }));
    expect(r).toMatchObject({ phase: "done", status: "maybe", profileState: "onboarded", links: null });
  });

  it("прошедшее событие — ошибка «недоступно»", async () => {
    login(1001);
    const { acceptInviteAction } = await actions();
    const r = await acceptInviteAction({ phase: "idle" }, form({ code: "MOCKPAST", slug: "stary-spektakl", day: "2026-10-10", status: "going" }));
    expect(r).toMatchObject({ phase: "error", error: "gone" });
  });

  it("сервер без профиля и без галочки в форме отвечает 409 → просим согласие", async () => {
    login(5002);
    const { acceptInviteAction } = await actions();
    const r = await acceptInviteAction({ phase: "idle" }, form({ ...base, status: "going" }));
    expect(r).toMatchObject({ phase: "error", error: "consent" });
  });
});

describe("«Позвать друга»", () => {
  it("создаёт приглашение: код, ссылка startapp и текст", async () => {
    login(1001);
    const { createInviteAction } = await actions();
    const r = await createInviteAction("karmannyj-ongon", "2026-10-24");
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.url).toContain(`startapp=inv_${r.code}`);
      expect(r.shareText).toContain("Пойдёшь со мной?");
    }
  });
  it("без сессии и с плохим слагом не создаёт", async () => {
    const { createInviteAction } = await actions();
    expect((await createInviteAction("karmannyj-ongon", null)).ok).toBe(false);
    login(1001);
    expect((await createInviteAction("../x", null)).ok).toBe(false);
  });
  it("приглашение, созданное человеком, открывается у него как «своё»", async () => {
    login(1001);
    const { createInviteAction } = await actions();
    const r = await createInviteAction("karmannyj-ongon", "2026-10-24");
    if (!r.ok) throw new Error("не создано");
    const { api } = await import("@/lib/api");
    expect((await api.invite(r.code, 1001)).inviter_is_me).toBe(true);
    expect((await api.invite(r.code, 4242)).inviter_is_me).toBe(false);
  });
});

describe("профиль и онбординг", () => {
  it("переключатель имени пишет show_name", async () => {
    login(1001);
    const { setShowNameAction } = await actions();
    const { api } = await import("@/lib/api");
    expect((await setShowNameAction(false)).ok).toBe(true);
    expect((await api.profile(1001)).show_name).toBe(false);
    expect((await setShowNameAction(true)).ok).toBe(true);
    expect((await api.profile(1001)).show_name).toBe(true);
  });

  it("два шага: пять ценностей, затем направления и бюджет → профиль готов, переход в дайджест", async () => {
    login(6001);
    const a = await actions();
    const { api } = await import("@/lib/api");
    const go = async (fn: () => Promise<void>) => fn().then(() => "", (e: Error) => e.message);

    jar.set("leisure_ref", "REFCODE1");
    expect(await go(() => a.startOnboardingAction(form({ consent: "on", needs_consent: "1" })))).toBe("REDIRECT:/profile?onboarding=1");
    expect(jar.get("leisure_ref")).toBe(""); // код рекомендации ушёл в API и очищен
    expect((await api.profile(6001)).source).toBe("ref");

    const top = ["Творчество", "Красота/эстетика", "Инновации/новизна", "Исследования", "Смысл"];
    const f1 = new FormData();
    top.forEach((v) => f1.append("top", v));
    expect(await go(() => a.saveOnboardingValuesAction(f1))).toBe("REDIRECT:/profile?onboarding=2");
    const mid = await api.profile(6001);
    expect(mid.onboarded).toBe(false); // после шага 1 профиль ещё не готов
    expect(Object.values(mid.values).filter((w) => w === 5)).toHaveLength(5);

    const f2 = form({ budget: "2500" });
    f2.append("cat", "Современное искусство");
    expect(await go(() => a.finishOnboardingAction(f2))).toBe("REDIRECT:/digest");
    const done = await api.profile(6001);
    expect(done.onboarded).toBe(true);
    expect(done.params.budget).toBe(2500);
    expect(done.interests["Современное искусство"]).toBe(3);
  });

  it("шаг 1 не принимает не пять ценностей", async () => {
    login(6002);
    const a = await actions();
    const f = new FormData();
    ["Творчество", "Покой"].forEach((v) => f.append("top", v));
    await expect(a.saveOnboardingValuesAction(f)).rejects.toThrow("REDIRECT:/profile?onboarding=1&error=5");
  });
});
