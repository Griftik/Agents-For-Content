import type { Decision, PlanItem } from "./api-types";

/** Прошедшие «иду» без отметки «сходил / не сходил»: точка на вкладке «План». */
export const unmarkedPast = (past: PlanItem[]): PlanItem[] => past.filter((it) => it.status === "иду" || it.status === "может");
export const hasUnmarkedPast = (past: PlanItem[] | undefined): boolean => unmarkedPast(past ?? []).length > 0;

/** Секция «Прошли»: неотмеченные первыми, затем отмеченные; свежие выше; не больше n. */
export function pastItems(past: PlanItem[] | undefined, n = 12): PlanItem[] {
  const rank = (it: PlanItem) => (it.status === "иду" || it.status === "может" ? 0 : 1);
  return [...(past ?? [])].sort((a, b) => rank(a) - rank(b) || b.day.localeCompare(a.day)).slice(0, n);
}

/** То же по решениям (для страниц без плана): «иду» с датой до сегодня. */
export const hasUnmarkedDecisions = (decisions: Decision[], today: string): boolean =>
  decisions.some((d) => d.status === "иду" && !!d.day && d.day < today);
