// Онбординг в Mini App (leisure/web/FLOW-ONBOARDING.md): пять ценностей из 19 по четырём группам, затем восемь направлений и бюджет.
// Подбор восьми направлений повторяет core/catalog.py (rank_categories / propose_interests); таблицу «направление → ценности»
// берём из каталога API (catalog.category_values), в коде её нет.

export const TOP_VALUES = 5;
export const PROPOSED_N = 8;
export const PROPOSED_TOP = 5;
export const BUDGETS: { value: number; label: string }[] = [
  { value: 1000, label: "до 1 000 ₽" },
  { value: 2500, label: "до 2 500 ₽" },
  { value: 0, label: "Не важно" },
];

/** Вес ценностей по выбору: выбранные пять = 5, остальные = 2 (нейтрально). */
export function weightsFromTop(all: string[], top: string[]): Record<string, number> {
  const t = new Set(top);
  return Object.fromEntries(all.map((v) => [v, t.has(v) ? 5 : 2]));
}

/** Пять названий из формы: только известные ценности, без повторов, ровно TOP_VALUES; иначе null. */
export function pickTop(all: string[], picked: string[]): string[] | null {
  const known = new Set(all);
  const uniq = [...new Set(picked)].filter((v) => known.has(v));
  return uniq.length === TOP_VALUES && uniq.length === picked.length ? uniq : null;
}

/** Группы ценностей для экрана: из каталога, а если их нет — одна группа «Ценности». */
export function clusters(all: string[], fromApi?: Record<string, string[]>): [string, string[]][] {
  if (!fromApi || !Object.keys(fromApi).length) return [["Ценности", all]];
  const entries = Object.entries(fromApi).map(([k, v]) => [k, v.filter((x) => all.includes(x))] as [string, string[]]);
  const seen = new Set(entries.flatMap(([, v]) => v));
  const rest = all.filter((v) => !seen.has(v));
  return rest.length ? [...entries, ["Ещё", rest]] : entries;
}

/** Насколько направление подходит ценностям: Σ вес ценности × вес связи. */
export function categoryFit(cat: string, values: Record<string, number>, table: Record<string, Record<string, number>>): number {
  return Object.entries(table[cat] ?? {}).reduce((sum, [v, w]) => sum + (values[v] ?? 0) * w, 0);
}

/**
 * Направления по убыванию подходящести (при равенстве — в порядке каталога). Если таблицы нет (бэкенд её пока не отдаёт),
 * порядок задают текущие интересы профиля, затем каталог.
 */
export function rankCategories(cats: string[], values: Record<string, number>, table?: Record<string, Record<string, number>>, interests: Record<string, number> = {}): string[] {
  const idx = new Map(cats.map((c, i) => [c, i]));
  const score = (c: string) => (table ? categoryFit(c, values, table) : (interests[c] ?? 0));
  return [...cats].sort((a, b) => score(b) - score(a) || idx.get(a)! - idx.get(b)!);
}

/** Уровни интересов 0–3 для сохранения: предложенные включённые — 3 (первые пять) и 2, выключенные — 0, прочие — 1 («иногда»). */
export function interestLevels(ranked: string[], enabled: Set<string>): Record<string, number> {
  const out: Record<string, number> = {};
  ranked.forEach((c, i) => {
    if (i >= PROPOSED_N) out[c] = 1;
    else out[c] = enabled.has(c) ? (i < PROPOSED_TOP ? 3 : 2) : 0;
  });
  return out;
}

export type OnboardingStep = "welcome" | "1" | "2";
export const parseStep = (v: string | undefined): OnboardingStep | null => (v === "welcome" || v === "1" || v === "2" ? v : v ? "1" : null);
