import "server-only";
import { ApiError } from "./api";

/** Результат загрузки: данные, «нет профиля» или сбой API — страница решает, что показать. */
export type Loaded<T> = { kind: "ok"; data: T } | { kind: "no-profile" } | { kind: "down"; message: string };

export async function load<T>(fn: () => Promise<T>): Promise<Loaded<T>> {
  try {
    return { kind: "ok", data: await fn() };
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.status === 404) return { kind: "no-profile" };
      return { kind: "down", message: e.status ? `${e.status}` : "нет связи" };
    }
    throw e;
  }
}
