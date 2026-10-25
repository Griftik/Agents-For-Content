"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import type { InviteAcceptStatus } from "@/lib/api-types";
import { REF_COOKIE, SESSION_COOKIE } from "@/lib/session-consts";
import { clearCookie, readRef } from "@/lib/cookies";
import { CODE_RE } from "@/lib/start-param";
import { BUDGETS, PROPOSED_N, TOP_VALUES, interestLevels, pickTop, rankCategories, weightsFromTop } from "@/lib/onboarding";
import { getProfileId, getUserId } from "@/lib/session";
import { PROFILE_COOKIE } from "@/lib/session-consts";
import { setProfileCookie } from "@/lib/cookies";
import { issueProfile, sessionSecret } from "@/lib/session-token";

const STATUSES = ["иду", "может", "интересно", "мимо", "пропуск", "не моё", "сходил", "не сходил"];
const str = (f: FormData, k: string) => {
  const v = f.get(k);
  return typeof v === "string" ? v.trim() : "";
};

/**
 * Решение по событию. Работает как обычная форма без JS и как server action с JS.
 * Повторное нажатие на уже выбранный статус (op=toggle, current) снимает решение; повторная причина «мимо» снимает причину.
 */
export async function decide(formData: FormData): Promise<void> {
  const uid = await getProfileId();
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
  const uid = await getProfileId();
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

const TRAVEL = { min: 10, max: 90 };

/** Сохранение профиля (v2): пять ценностей чипами, направления 0–3, бюджет, время, дорога, имя профиля. */
export async function saveProfile(formData: FormData): Promise<void> {
  const uid = await getProfileId();
  if (!uid) redirect("/profile");
  const picked = formData.getAll("top").filter((x): x is string => typeof x === "string");
  const interests: Record<string, number> = {};
  for (const [k, v] of formData.entries()) if (typeof v === "string" && k.startsWith("i:")) interests[k.slice(2)] = clamp(Number(v), 0, 3);
  const budget = Number(str(formData, "budget") || 0);
  const travelRaw = Number(str(formData, "travel"));
  const params = {
    budget: Number.isFinite(budget) ? clamp(budget, 0, 1_000_000) : 0,
    times: formData.getAll("times").filter((x): x is string => typeof x === "string"),
    travel_minutes: Number.isFinite(travelRaw) ? clamp(travelRaw, TRAVEL.min, TRAVEL.max) : 40,
  };
  let target = "/profile?saved=1";
  try {
    const catalog = await api.catalog();
    const top = pickTop(catalog.values, picked);
    if (!top) redirect(`/profile?error=${encodeURIComponent("Выбери ровно пять ценностей")}`);
    await api.saveProfile(uid, { values: weightsFromTop(catalog.values, top), interests, params, name: str(formData, "name").slice(0, 80) || undefined });
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    target = `/profile?error=${encodeURIComponent(e.status === 422 ? "Проверь значения: что-то не прошло проверку" : "Не удалось сохранить, попробуй ещё раз")}`;
  }
  revalidatePath("/digest");
  redirect(target);
}

/** «Что я о тебе узнал»: Больше / Меньше / Сбросить по тегу или категории — ручная правка affinity (PUT affinity). */
export async function tweakLearnedAction(kind: "tag" | "cat", key: string, op: "more" | "less" | "reset"): Promise<{ ok: boolean }> {
  const uid = await getProfileId();
  if (!uid || !key || key.length > 80 || (kind !== "tag" && kind !== "cat")) return { ok: false };
  try {
    const p = await api.profile(uid);
    const cur = Number(p.affinity?.[kind]?.[key] ?? 0);
    const next = op === "reset" ? 0 : clamp(cur + (op === "more" ? 1 : -1), -5, 5);
    await api.saveProfile(uid, { affinity: { [kind]: { [key]: next } } });
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    return { ok: false };
  }
  revalidatePath("/profile");
  revalidatePath("/digest");
  return { ok: true };
}

// ─── Лента и план (v2) ───

export type FeedDecision = "иду" | "не моё";

/** Карточка ленты: «Иду» или «Не моё». Возвращает ok и, для «Иду», ссылку на событие для нижнего листа. */
export async function feedDecideAction(slug: string, day: string, status: FeedDecision): Promise<{ ok: boolean }> {
  const uid = await getProfileId();
  if (!uid || !SLUG_RE.test(slug) || !DAY_RE.test(day) || (status !== "иду" && status !== "не моё")) return { ok: false };
  try {
    await api.decide({ user_id: uid, event: slug, status, day });
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    return { ok: false };
  }
  revalidatePath("/plan");
  return { ok: true };
}

/** «Отменить» в тосте (5 секунд): решение снимается. */
export async function undoDecisionAction(slug: string): Promise<{ ok: boolean }> {
  const uid = await getProfileId();
  if (!uid || !SLUG_RE.test(slug)) return { ok: false };
  try {
    await api.removeDecision(uid, slug);
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    return { ok: false };
  }
  revalidatePath("/plan");
  return { ok: true };
}

export type RateResult = { ok: boolean; refAsk?: { url: string; shareText: string } | null; askReason?: boolean };

/** Прошедшее событие в плане: «Сходил» / «Не сходил»; оценка ★1–5 после «Сходил». API сам решает про момент рекомендации (ref_ask). */
export async function markPastAction(slug: string, went: boolean, rating?: number): Promise<RateResult> {
  const uid = await getProfileId();
  if (!uid || !SLUG_RE.test(slug) || (rating != null && (!Number.isInteger(rating) || rating < 1 || rating > 5))) return { ok: false };
  try {
    const r = (await api.decide({ user_id: uid, event: slug, status: went ? "сходил" : "не сходил", rating: went ? rating : undefined })) as {
      ref_ask?: { url?: string | null; share_text?: string } | null;
      ask_reason?: boolean;
    };
    revalidatePath("/plan");
    const ra = r.ref_ask;
    return { ok: true, refAsk: ra?.share_text ? { url: ra.url || "", shareText: ra.share_text } : null, askReason: !!r.ask_reason };
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    return { ok: false };
  }
}

// ─── Профили аккаунта («я», «мама», «ребёнок») ───

const KINDS = ["parent", "child", "other"];

/** Переключение активного профиля: проверяем, что он принадлежит аккаунту, и пишем подписанный cookie. */
export async function switchProfileAction(profileId: number): Promise<void> {
  const uid = await getUserId();
  const secret = sessionSecret(process.env);
  if (!uid || !secret || !Number.isSafeInteger(profileId) || profileId <= 0) redirect("/profile");
  try {
    const list = await api.profiles(uid);
    if (!list.some((p) => p.id === profileId)) redirect("/profile");
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    redirect("/profile");
  }
  await setProfileCookie(issueProfile(profileId, uid, secret));
  revalidatePath("/", "layout");
  redirect("/digest");
}

/** Новый профиль в аккаунте: имя и вид, затем сразу его онбординг (два шага). */
export async function createProfileAction(formData: FormData): Promise<void> {
  const uid = await getUserId();
  const secret = sessionSecret(process.env);
  const name = str(formData, "pname").slice(0, 40);
  const kind = str(formData, "kind");
  if (!uid || !secret) redirect("/profile");
  if (!name) redirect(`/profile?error=${encodeURIComponent("Дай профилю имя")}`);
  try {
    const p = await api.createProfile(uid, name, KINDS.includes(kind) ? kind : "other");
    await setProfileCookie(issueProfile(p.id, uid, secret));
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    redirect(`/profile?error=${encodeURIComponent("Не получилось создать профиль, попробуй ещё раз")}`);
  }
  revalidatePath("/", "layout");
  redirect("/profile?onboarding=1");
}

// ─── Приглашения ───

const SLUG_RE = /^[A-Za-z0-9_-]{1,120}$/;
const DAY_RE = /^\d{4}-\d{2}-\d{2}$/;

export type ShareResult = { ok: true; code: string; url: string; shareText: string } | { ok: false; error: string };

/** «Позвать друга»: создаёт (или находит прежнее) приглашение на событие и день. Вызывается из клиента, дальше он открывает «Поделиться». */
export async function createInviteAction(slug: string, day: string | null): Promise<ShareResult> {
  const uid = await getProfileId();
  if (!uid) return { ok: false, error: "Приложение ещё готовится, попробуй через секунду." };
  if (!SLUG_RE.test(slug) || (day && !DAY_RE.test(day))) return { ok: false, error: "Не получилось создать приглашение." };
  try {
    const inv = await api.createInvite(uid, slug, day);
    // ссылка — обычный адрес приложения (web_url на WEB_BASE_URL); url из API — запасной
    const url = inv.web_url || inv.url;
    if (!inv.code || !url) return { ok: false, error: "Не получилось создать приглашение, попробуй ещё раз." };
    return { ok: true, code: inv.code, url, shareText: inv.share_text };
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    return { ok: false, error: e.status === 404 ? "Сначала познакомимся: профиль появится после онбординга." : e.status === 410 ? "Это событие снято с публикации." : "Не получилось создать приглашение, попробуй ещё раз." };
  }
}

export type DoneLinks = { gcal: string; outlook: string; ics: string };
export type AcceptState =
  | { phase: "idle" }
  | { phase: "error"; error: "consent" | "no-session" | "gone" | "down"; message: string }
  | { phase: "done"; status: InviteAcceptStatus; togetherWith: string | null; profileState: "new" | "onboarded"; links: DoneLinks | null };

/** «Иду вместе» / «Может быть» по приглашению. Без профиля нужна галочка согласия: она уходит в API как consent=true. */
export async function acceptInviteAction(_prev: AcceptState, formData: FormData): Promise<AcceptState> {
  const uid = await getProfileId();
  if (!uid) return { phase: "error", error: "no-session", message: "no-session" };
  const code = str(formData, "code");
  const slug = str(formData, "slug");
  const status = str(formData, "status");
  const day = str(formData, "day");
  if (!CODE_RE.test(code) || (status !== "going" && status !== "maybe")) return { phase: "error", error: "down", message: "bad-request" };
  const consent = formData.get("consent") === "on";
  if (str(formData, "needs_consent") === "1" && !consent) return { phase: "error", error: "consent", message: "consent" };

  // Имя необязательно: гостю его взять неоткуда, кроме поля на странице; пригласивший увидит «Друг идёт с тобой», если оно пустое.
  const name = str(formData, "name").slice(0, 80);
  let accepted;
  try {
    accepted = await api.acceptInvite(code, { user_id: uid, status, consent, name: name || undefined });
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

/** «Другие выходные под меня»: приглашение помечается declined (пригласивший не уведомляется), дальше «Дайджест» или онбординг. */
export async function declineInviteAction(formData: FormData): Promise<void> {
  const uid = await getProfileId();
  const code = str(formData, "code");
  if (!uid) redirect("/digest");
  let hasProfile = false; // профиль после declined не ожидаем: без согласия API его не создаёт
  try {
    hasProfile = !!(await api.profile(uid)).has_consent;
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
  }
  if (CODE_RE.test(code)) {
    try {
      await api.acceptInvite(code, { user_id: uid, status: "declined", consent: false });
    } catch (e) {
      if (!(e instanceof ApiError)) throw e; // отметка не обязательна: переход важнее
    }
  }
  redirect(hasProfile ? "/digest" : "/profile?onboarding=welcome");
}

/** «Потом» на предложении подборки: offer_seen = 1; повтор покажет layout, когда наступит profile.offer_due (день события + 1). */
export async function postponeOfferAction(): Promise<void> {
  await setOfferSeen(1);
}
/** Повтор показан, «Давай» или «Не нужно»: больше не предлагаем (offer_seen = 2). */
export async function dropOfferAction(): Promise<void> {
  await setOfferSeen(2);
}
async function setOfferSeen(n: 1 | 2): Promise<void> {
  const uid = await getProfileId();
  if (!uid) return;
  try {
    await api.saveProfile(uid, { offer_seen: n });
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
  }
}

/** Страница приглашения показана: учёт открытия (POST /api/invites/{код}/open). Без согласия профиль не создаётся, считается только открытие. */
export async function openInviteAction(code: string): Promise<void> {
  const uid = await getProfileId();
  if (!uid || !CODE_RE.test(code)) return;
  try {
    await api.openInvite(code, { user_id: uid });
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
  }
}

/** Переключатель «Показывать имя друзьям» в профиле: PUT /api/profile show_name. */
export async function setShowNameAction(show: boolean): Promise<{ ok: boolean }> {
  const uid = await getProfileId();
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

// ─── Онбординг (два шага) ───

/** Приветствие: согласие (если его ещё нет), необязательное имя и создание профиля с кодом рекомендации, если он был в ссылке. */
export async function startOnboardingAction(formData: FormData): Promise<void> {
  const uid = await getUserId();
  if (!uid) redirect("/profile?onboarding=welcome");
  const consent = formData.get("consent") === "on";
  if (formData.get("needs_consent") === "1" && !consent) redirect("/profile?onboarding=welcome&need=consent");
  const name = str(formData, "name").slice(0, 80);
  const ref = await readRef();
  try {
    // Согласие, имя и код рекомендации одним PUT (профиль создаётся здесь); затем /open учитывает открытие ref-ссылки.
    await api.saveProfile(uid, { consent: consent || undefined, name: name || undefined, ref_code: ref ?? undefined });
    if (ref) await api.openInvite(ref, { user_id: uid }).catch((e) => {
      if (!(e instanceof ApiError)) throw e;
    });
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    redirect("/profile?onboarding=welcome&error=1");
  }
  if (ref) await clearCookie(REF_COOKIE);
  redirect("/profile?onboarding=1");
}

/** Шаг 1 из 2: пять главных ценностей (вес 5), остальные получают 2. Интересы пока не пишем: запись интересов помечает профиль готовым. */
export async function saveOnboardingValuesAction(formData: FormData): Promise<void> {
  const uid = await getProfileId();
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
  const uid = await getProfileId();
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
      params: { budget, aesthetics: top.includes("Красота/эстетика"), times: ["день", "вечер"], adults30: true, kids: false, company: "любая", areas: ["любой"], travel_minutes: 40 },
      onboarded: true,
    });
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    redirect("/profile?onboarding=2&error=save");
  }
  revalidatePath("/digest");
  redirect("/digest?day=today");
}

// ─── Рекомендация, почта, удаление данных ───

/** Момент рекомендации после оценки 4–5: ссылка-рекомендация (kind=ref) и текст «Поделиться». */
export async function createReferralAction(): Promise<ShareResult> {
  const uid = await getProfileId();
  if (!uid) return { ok: false, error: "Приложение ещё готовится, попробуй через секунду." };
  try {
    const inv = await api.createReferral(uid);
    const url = inv.web_url || inv.url;
    if (!inv.code || !url) return { ok: false, error: "Не получилось создать ссылку, попробуй ещё раз." };
    return { ok: true, code: inv.code, url, shareText: inv.share_text };
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    return { ok: false, error: "Не получилось создать ссылку, попробуй ещё раз." };
  }
}

export type EmailState = { phase: "idle" } | { phase: "sent" } | { phase: "later" } | { phase: "error"; message: string };

/** Привязка почты: ссылка-вход на адрес. 503 — у API нет SMTP, показываем «почта подключится позже». */
export async function linkEmailAction(_prev: EmailState, formData: FormData): Promise<EmailState> {
  const uid = await getUserId();
  const email = str(formData, "email").toLowerCase();
  if (!uid) return { phase: "error", message: "Приложение ещё готовится, попробуй через секунду." };
  if (!/^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$/.test(email)) return { phase: "error", message: "Проверь адрес почты." };
  try {
    await api.linkEmail(uid, email);
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    if (e.status === 503) return { phase: "later" };
    return { phase: "error", message: e.status === 422 ? "Проверь адрес почты." : "Не получилось отправить письмо. Проверь адрес и попробуй ещё раз." };
  }
  return { phase: "sent" };
}

/** «Удалить мои данные»: профиль, решения, подписки на push; сессия сбрасывается. */
export async function deleteDataAction(): Promise<void> {
  const uid = await getUserId();
  if (!uid) redirect("/");
  try {
    await api.deleteProfile(uid);
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    redirect("/profile?error=" + encodeURIComponent("Не получилось удалить, попробуй ещё раз"));
  }
  await clearCookie(SESSION_COOKIE);
  await clearCookie(REF_COOKIE);
  await clearCookie(PROFILE_COOKIE);
  redirect("/?deleted=1");
}
