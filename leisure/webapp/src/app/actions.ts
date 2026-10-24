"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { api, ApiError } from "@/lib/api";
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
