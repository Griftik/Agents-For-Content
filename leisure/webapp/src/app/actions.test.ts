import { beforeEach, describe, expect, it, vi } from "vitest";
import { SESSION_COOKIE } from "@/lib/session-consts";
import { issueSession } from "@/lib/session-token";
import { resetMock } from "@/lib/mock";
import { addDays } from "@/lib/feed";
import { moscowToday } from "@/lib/format";

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
  jar.clear();
  resetMock();
});

const actions = () => import("./actions");
const base = { code: "MOCKOK01", slug: "karmannyj-ongon", day: addDays(moscowToday(), 1) };

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
    expect(r.links?.ics).toBe(`/api/events/karmannyj-ongon/ics?day=${base.day}`);
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
    const r = await acceptInviteAction({ phase: "idle" }, form({ code: "MOCKPAST", slug: "stary-spektakl", day: addDays(moscowToday(), -15), status: "going" }));
    expect(r).toMatchObject({ phase: "error", error: "gone" });
  });

  it("сервер без профиля и без галочки в форме отвечает 409 → просим согласие", async () => {
    login(5002);
    const { acceptInviteAction } = await actions();
    const r = await acceptInviteAction({ phase: "idle" }, form({ ...base, status: "going" }));
    expect(r).toMatchObject({ phase: "error", error: "consent" });
  });
});

describe("предложение подборки и учёт открытия", () => {
  it("«Потом» и «Не нужно» пишут offer_seen в профиль (cookie не используется)", async () => {
    login(1002);
    const { postponeOfferAction, dropOfferAction } = await actions();
    const { api } = await import("@/lib/api");
    await postponeOfferAction();
    expect((await api.profile(1002)).offer_seen).toBe(1);
    await dropOfferAction();
    expect((await api.profile(1002)).offer_seen).toBe(2);
    expect([...jar.keys()].some((k) => k.includes("offer"))).toBe(false);
  });
  it("открытие приглашения не создаёт профиль без согласия", async () => {
    login(5100);
    const { openInviteAction } = await actions();
    const { api } = await import("@/lib/api");
    await openInviteAction("MOCKOK01");
    await expect(api.profile(5100)).rejects.toThrow();
  });
  it("«иду» ставит offer_due = день события + 1", async () => {
    login(5101);
    const { acceptInviteAction } = await actions();
    const { api } = await import("@/lib/api");
    await acceptInviteAction({ phase: "idle" }, form({ ...base, status: "going", needs_consent: "1", consent: "on" }));
    expect((await api.profile(5101)).offer_due).toBe(addDays(base.day, 1));
  });
});

describe("«Другие выходные под меня»", () => {
  it("помечает declined и ведёт в дайджест (есть профиль) или в онбординг (нет)", async () => {
    const { declineInviteAction } = await actions();
    login(1001);
    await expect(declineInviteAction(form({ code: "MOCKOK01" }))).rejects.toThrow("REDIRECT:/digest");
    jar.clear();
    login(5009);
    await expect(declineInviteAction(form({ code: "MOCKOK01" }))).rejects.toThrow("REDIRECT:/profile?onboarding=welcome");
  });
});

describe("«Позвать друга»", () => {
  it("создаёт приглашение: код, ссылка startapp и текст", async () => {
    login(1001);
    const { createInviteAction } = await actions();
    const r = await createInviteAction("karmannyj-ongon", "2026-10-24");
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.url).toContain(`/e/karmannyj-ongon?inv=${r.code}`);
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
    expect((await api.invite(r.code, 1001)).is_own).toBe(true);
    expect((await api.invite(r.code, 4242)).is_own).toBe(false);
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
    expect(await go(() => a.finishOnboardingAction(f2))).toBe("REDIRECT:/digest?day=today");
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

describe("лента и план (v2)", () => {
  it("«Иду» и «Не моё» с карточки, «Отменить» снимает решение", async () => {
    login(1001);
    const { feedDecideAction, undoDecisionAction } = await actions();
    const { api } = await import("@/lib/api");
    const feed = await api.feed(1001, "week", "leisure");
    const it0 = feed.items[0];
    expect((await feedDecideAction(it0.event.slug, it0.day, "иду")).ok).toBe(true);
    expect((await api.decisions(1001)).find((d) => d.event_slug === it0.event.slug)?.status).toBe("иду");
    expect((await feedDecideAction(feed.items[1].event.slug, feed.items[1].day, "не моё")).ok).toBe(true);
    expect((await undoDecisionAction(it0.event.slug)).ok).toBe(true);
    expect((await api.decisions(1001)).some((d) => d.event_slug === it0.event.slug)).toBe(false);
    expect((await feedDecideAction("../x", it0.day, "иду")).ok).toBe(false);
  });
  it("прошедшее: «Сходил» с оценкой 5 даёт момент рекомендации, «Не сходил» — нет", async () => {
    login(1001);
    const { markPastAction } = await actions();
    const r = await markPastAction("f-proshloe", true, 5);
    expect(r.ok).toBe(true);
    expect(r.refAsk?.shareText).toContain("http");
    const n = await markPastAction("f-proshloe", false);
    expect(n).toMatchObject({ ok: true, refAsk: null });
    expect((await markPastAction("f-proshloe", true, 9)).ok).toBe(false);
  });
});

describe("профили аккаунта", () => {
  it("новый профиль ставит подписанный cookie и ведёт в его онбординг; чужой id не переключает", async () => {
    login(1001);
    const a = await actions();
    const f = form({ pname: "Мама", kind: "parent" });
    await expect(a.createProfileAction(f)).rejects.toThrow("REDIRECT:/profile?onboarding=1");
    expect(jar.get("leisure_profile")).toMatch(/^\d+\.1001\./);
    const { getProfileId } = await import("@/lib/session");
    const pid = await getProfileId();
    expect(pid).not.toBe(1001);
    await expect(a.switchProfileAction(1001)).rejects.toThrow("REDIRECT:/digest");
    expect(await getProfileId()).toBe(1001);
    await expect(a.switchProfileAction(424242)).rejects.toThrow("REDIRECT:/profile");
    expect(await getProfileId()).toBe(1001);
  });
  it("сохранение профиля v2: пять ценностей, направления, бюджет, дорога", async () => {
    login(1001);
    const a = await actions();
    const { api } = await import("@/lib/api");
    const f = form({ budget: "2500", travel: "25", "i:Джаз": "3", "i:Театр": "0", name: "Мария" });
    ["Творчество", "Покой", "Семья", "Природа", "Смысл"].forEach((v) => f.append("top", v));
    f.append("times", "вечер");
    await expect(a.saveProfile(f)).rejects.toThrow("REDIRECT:/profile?saved=1");
    const p = await api.profile(1001);
    expect(p.values["Покой"]).toBe(5);
    expect(p.values["Творчество"]).toBe(5);
    expect(p.values["Джаз" as never]).toBeUndefined();
    expect(p.interests["Джаз"]).toBe(3);
    expect(p.interests["Театр"]).toBe(0);
    expect(p.params.budget).toBe(2500);
    expect(p.params.travel_minutes).toBe(25);
    expect(p.params.times).toEqual(["вечер"]);
  });
  it("«что я о тебе узнал»: Больше / Меньше / Сбросить правят affinity", async () => {
    login(1001);
    const a = await actions();
    const { api } = await import("@/lib/api");
    expect((await a.tweakLearnedAction("cat", "Джаз", "more")).ok).toBe(true);
    expect((await api.profile(1001)).affinity?.cat?.["Джаз"]).toBe(1);
    await a.tweakLearnedAction("cat", "Джаз", "less");
    await a.tweakLearnedAction("cat", "Джаз", "less");
    expect((await api.profile(1001)).affinity?.cat?.["Джаз"]).toBe(-1);
    await a.tweakLearnedAction("cat", "Джаз", "reset");
    expect((await api.profile(1001)).affinity?.cat?.["Джаз"]).toBe(0);
  });
});

describe("аккаунт", () => {
  it("почта: 503 от API → «подключится позже», плохой адрес не уходит", async () => {
    login(1001);
    const { linkEmailAction } = await actions();
    expect(await linkEmailAction({ phase: "idle" }, form({ email: "мусор" }))).toMatchObject({ phase: "error" });
    expect(await linkEmailAction({ phase: "idle" }, form({ email: "a@b.cc" }))).toEqual({ phase: "later" });
    vi.stubEnv("MOCK_SMTP", "1");
    expect(await linkEmailAction({ phase: "idle" }, form({ email: "a@b.cc" }))).toEqual({ phase: "sent" });
  });
  it("«Удалить мои данные» стирает профиль и сбрасывает сессию", async () => {
    login(1001);
    const { deleteDataAction } = await actions();
    const { api } = await import("@/lib/api");
    await expect(deleteDataAction()).rejects.toThrow("REDIRECT:/?deleted=1");
    await expect(api.profile(1001)).rejects.toThrow();
    expect(jar.get(SESSION_COOKIE)).toBe("");
  });
});
