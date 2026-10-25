import type { Decision } from "./api-types";

/** Прошедшие «иду» без отметки «сходил / не сходил»: точка на вкладке «План». */
export const unmarkedPast = (decisions: Decision[], today: string): Decision[] =>
  decisions.filter((d) => d.status === "иду" && !!d.day && d.day < today);
export const hasUnmarkedPast = (decisions: Decision[], today: string): boolean => unmarkedPast(decisions, today).length > 0;

/** Прошедшие решения для секции «Прошли»: «иду» без отметки первыми, затем отмеченные; не больше n. */
export function pastDecisions(decisions: Decision[], today: string, n = 12): Decision[] {
  const past = decisions.filter((d) => !!d.day && d.day < today && (d.status === "иду" || d.status === "сходил" || d.status === "не сходил"));
  return past.sort((a, b) => (a.status === "иду" ? 0 : 1) - (b.status === "иду" ? 0 : 1) || (b.day ?? "").localeCompare(a.day ?? "")).slice(0, n);
}
