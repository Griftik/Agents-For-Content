"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import type { InviteAcceptStatus, Profile } from "@/lib/api-types";
import { OFFER_COOKIE, REF_COOKIE } from "@/lib/session-consts";
import { clearCookie, readRef, readWho, setOffer } from "@/lib/cookies";
import { CODE_RE } from "@/lib/start-param";
import { BUDGETS, PROPOSED_N, TOP_VALUES, interestLevels, pickTop, rankCategories, weightsFromTop } from "@/lib/onboarding";
import { getUserId } from "@/lib/session";

const STATUSES = ["иду", "может", "интересно", "мимо", "пропуск"];
const str = (f: FormData, k: string) => {
  const v = f.get(k);
  return typeof v === "string" ? v.trim() : "";
};

/**
 * Решение по событию. Работает как обычная форма без JS и как server action с JS.
 * Повторное нажатие на уже выбранный статус (op=toggle, current) снимает решение; повторная причина «мимо» снимает причину.
 */
export async function decide(formData: FormData): Promise<void> {
  const uid = await getUserId();
  if (!uid) return;
  const slug = str(formData, "slug");
  const status = str(formData, "status");
  const current = str(formData, "current");
  const currentReason = str(formData, "current_reason");
  const currentDay = str(formData, "current_day");
  const toggle = str(formData, "op") === "toggle";
  const reason = str(formData, "reason");
  const day = str(formData, "day");
  if (!/^[A-Za-z0-9_-]{1,120}$/.test(slug) || !STATUSES.includes(status)) return;

  try {
    if (toggle && status === current) {
      await api.removeDecision(uid, slug);
    } else {
      await api.decide({
        user_id: uid,
        event: slug,
        status,
        reason: reason && reason !== currentReason ? reason : undefined,
        day: /^\d{4}-\d{2}-\d{2}$/.test(day) && day !== currentDay ? day : undefined,
      });
    }
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
  }
  revalidatePath("/digest");
  revalidatePath("/plan");
}

/** «Убрать» из плана. */
export async function removeFromPlan(formData: FormData): Promise<void> {
  const uid = await getUserId();
  const slug = str(formData, "slug");
  if (!uid || !/^[A-Za-z0-9_-]{1,120}$/.test(slug)) return;
  try {
    await api.removeDecision(uid, slug);
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
  }
  revalidatePath("/plan");
  revalidatePath("/digest");
}

const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, Math.round(n)));

/** Сохранение профиля: PUT с изменёнными разделами. */
export async function saveProfile(formData: FormData): Promise<void> {
  const uid = await getUserId();
  if (!uid) redirect("/profile");

  const values: Record<string, number> = {};
  const interests: Record<string, number> = {};
  for (const [k, v] of formData.entries()) {
    if (typeof v !== "string") continue;
    if (k.startsWith("v:")) values[k.slice(2)] = clamp(Number(v), 0, 5);
    else if (k.startsWith("i:")) interests[k.slice(2)] = clamp(Number(v), 0, 3);
  }
  const budget = Number(str(formData, "budget") || 0);
  const params = {
    aesthetics: formData.get("aesthetics") === "on",
    adults30: formData.get("adults30") === "on",
    kids: formData.get("kids") === "on",
    budget: Number.isFinite(budget) ? clamp(budget, 0, 1_000_000) : 0,
    company: str(formData, "company") || undefined,
    times: formData.getAll("times").filter((x): x is string => typeof x === "string"),
    // районы вне списка (введённые в боте) сохраняем как были
    areas: formData.getAll("areas").filter((x): x is string => typeof x === "string"),
  };
  let target = "/profile?saved=1";
  try {
    await api.saveProfile(uid, { values, interests, params, notes: String(formData.get("notes") ?? "").slice(0, 2000) });
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    target = `/profile?error=${encodeURIComponent(e.status === 422 ? "Проверь значения: что-то не прошло проверку" : "Не удалось сохранить, попробуй ещё раз")}`;
  }
  revalidatePath("/digest");
  redirect(target);
}

// ─── Приглашения ───

const SLUG_RE = /^[A-Za-z0-9_-]{1,120}$/;
const DAY_RE = /^\d{4}-\d{2}-\d{2}$/;

export type ShareResult = { ok: true; code: string; url: string; shareText: string } | { ok: false; error: string };

/** «Позвать друга»: создаёт (или находит прежнее) приглашение на событие и день. Вызывается из клиента, дальше он открывает «Поделиться». */
export async function createInviteAction(slug: string, day: string | null): Promise<ShareResult> {
  const uid = await getUserId();
  if (!uid) return { ok: false, error: "Открой приложение из Telegram, и кнопка заработает." };
  if (!SLUG_RE.test(slug) || (day && !DAY_RE.test(day))) return { ok: false, error: "Не получилось создать приглашение." };
  try {
    const ev = await api.event(slug);
    const inv = await api.createInvite(uid, ev, day);
    if (!inv.code || !inv.url) return { ok: false, error: "Не получилось создать приглашение, попробуй ещё раз." };
    return { ok: true, code: inv.code, url: inv.url, shareText: inv.share_text };
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    return { ok: false, error: e.status === 404 ? "Сначала познакомимся: профиль появится после онбординга." : "Не получилось создать приглашение, попробуй ещё раз." };
  }
}

export type DoneLinks = { gcal: string; outlook: string; ics: string };
export type AcceptState =
  | { phase: "idle" }
  | { phase: "error"; error: "consent" | "no-session" | "gone" | "down"; message: string }
  | { phase: "done"; status: InviteAcceptStatus; togetherWith: string | null; profileState: "new" | "onboarded"; links: DoneLinks | null };

/** «Иду вместе» / «Может быть» по приглашению. Без профиля нужна галочка согласия: она уходит в API как consent=true. */
export async function acceptInviteAction(_prev: AcceptState, formData: FormData): Promise<AcceptState> {
  const uid = await getUserId();
  if (!uid) return { phase: "error", error: "no-session", message: "no-session" };
  const code = str(formData, "code");
  const slug = str(formData, "slug");
  const status = str(formData, "status");
  const day = str(formData, "day");
  if (!CODE_RE.test(code) || (status !== "going" && status !== "maybe")) return { phase: "error", error: "down", message: "bad-request" };
  const consent = formData.get("consent") === "on";
  if (str(formData, "needs_consent") === "1" && !consent) return { phase: "error", error: "consent", message: "consent" };

  const who = await readWho();
  let prof: Profile | null = null;
  try {
    prof = await api.profile(uid);
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    if (e.status !== 404) return { phase: "error", error: "down", message: String(e.status) };
  }
  let accepted;
  try {
    accepted = await api.acceptInvite(
      code,
      { user_id: uid, status, consent, name: who.name || undefined, username: who.username || undefined },
      prof?.onboarded ? "onboarded" : "new",
    );
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    if (e.status === 409) return { phase: "error", error: "consent", message: "consent" };
    if (e.status === 410) return { phase: "error", error: "gone", message: e.message };
    return { phase: "error", error: "down", message: String(e.status) };
  }

  // Календари «как на карточке»: ссылки берём из плана (Google, Outlook), .ics — наш маршрут.
  let links: DoneLinks | null = null;
  if (status === "going" && SLUG_RE.test(slug)) {
    const d = DAY_RE.test(day) ? day : accepted.decision?.day ?? "";
    try {
      const plan = await api.plan(uid);
      const it = [...Object.values(plan.days).flat(), ...plan.horizon].find((x) => x.event.slug === slug && (!d || x.day === d));
      links = it
        ? { gcal: it.links.gcal, outlook: it.links.outlook, ics: `/api/events/${slug}/ics?day=${it.day}` }
        : d ? { gcal: "", outlook: "", ics: `/api/events/${slug}/ics?day=${d}` } : null;
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
    }
  }
  revalidatePath("/digest");
  revalidatePath("/plan");
  return { phase: "done", status, togetherWith: accepted.together_with, profileState: accepted.profile_state, links };
}

/** «Потом» на предложении подборки: запоминаем день события, после него предложение покажется ещё раз. */
export async function postponeOfferAction(day: string): Promise<void> {
  if (DAY_RE.test(day)) await setOffer(day);
}
/** «Не нужно» или «Давай» на повторе: больше не предлагаем. */
export async function dropOfferAction(): Promise<void> {
  await clearCookie(OFFER_COOKIE);
}

/** Переключатель «Показывать имя друзьям» в профиле: PUT /api/profile show_name. */
export async function setShowNameAction(show: boolean): Promise<{ ok: boolean }> {
  const uid = await getUserId();
  if (!uid) return { ok: false };
  try {
    await api.saveProfile(uid, { show_name: show });
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    return { ok: false };
  }
  revalidatePath("/profile");
  return { ok: true };
}

// ─── Онбординг в Mini App (два шага) ───

/** Приветствие: согласие (если профиля ещё нет) и создание профиля с кодом рекомендации, если он был в start_param. */
export async function startOnboardingAction(formData: FormData): Promise<void> {
  const uid = await getUserId();
  if (!uid) redirect("/profile?onboarding=welcome");
  const consent = formData.get("consent") === "on";
  if (formData.get("needs_consent") === "1" && !consent) redirect("/profile?onboarding=welcome&need=consent");
  const who = await readWho();
  const ref = await readRef();
  try {
    await api.saveProfile(uid, { consent: consent || undefined, name: who.name || undefined, username: who.username || undefined, ref_code: ref ?? undefined });
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    redirect("/profile?onboarding=welcome&error=1");
  }
  if (ref) await clearCookie(REF_COOKIE);
  redirect("/profile?onboarding=1");
}

/** Шаг 1 из 2: пять главных ценностей (вес 5), остальные получают 2. Интересы пока не пишем: запись интересов помечает профиль готовым. */
export async function saveOnboardingValuesAction(formData: FormData): Promise<void> {
  const uid = await getUserId();
  if (!uid) redirect("/profile?onboarding=1");
  const picked = formData.getAll("top").filter((x): x is string => typeof x === "string");
  let target = "/profile?onboarding=2";
  try {
    const catalog = await api.catalog();
    const top = pickTop(catalog.values, picked);
    if (!top) redirect(`/profile?onboarding=1&error=${TOP_VALUES}`);
    await api.saveProfile(uid, { values: weightsFromTop(catalog.values, top) });
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    target = "/profile?onboarding=1&error=save";
  }
  redirect(target);
}

/** Шаг 2 из 2: восемь направлений (вкл/выкл), бюджет; профиль становится готовым, дальше «Дайджест». */
export async function finishOnboardingAction(formData: FormData): Promise<void> {
  const uid = await getUserId();
  if (!uid) redirect("/profile?onboarding=2");
  const enabled = new Set(formData.getAll("cat").filter((x): x is string => typeof x === "string"));
  const budgetRaw = Number(str(formData, "budget"));
  const budget = BUDGETS.some((b) => b.value === budgetRaw) ? budgetRaw : 0;
  try {
    const [catalog, prof] = await Promise.all([api.catalog(), api.profile(uid)]);
    const cats = [...catalog.categories, ...(catalog.business_categories ?? [])];
    const ranked = rankCategories(cats, prof.values, catalog.category_values, prof.interests);
    const proposed = new Set(ranked.slice(0, PROPOSED_N));
    const top = Object.entries(prof.values).filter(([, w]) => w >= 5).map(([k]) => k);
    await api.saveProfile(uid, {
      // выключить можно только предложенные: остальным остаётся «иногда»
      interests: interestLevels(ranked, new Set([...enabled].filter((c) => proposed.has(c)))),
      params: { budget, aesthetics: top.includes("Красота/эстетика"), times: ["день", "вечер"], adults30: true, kids: false, company: "любая", areas: ["любой"] },
      onboarded: true,
    });
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    redirect("/profile?onboarding=2&error=save");
  }
  await clearCookie(OFFER_COOKIE);
  revalidatePath("/digest");
  redirect("/digest");
}
