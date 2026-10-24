import "server-only";
import { apiBase, apiKey } from "./config";
import type { Catalog, Decision, Digest, EventT, Plan, Profile, ProfilePatch, ScoredEvent } from "./api-types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

const TIMEOUT_MS = 8000;

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(apiBase() + path, {
    ...init,
    cache: "no-store",
    signal: AbortSignal.timeout(TIMEOUT_MS),
    // Ключ добавляется только здесь, на сервере; в браузер он не попадает.
    headers: { Accept: "application/json", "X-API-Key": apiKey(), ...(init.headers ?? {}) },
  }).catch((e: unknown) => {
    throw new ApiError(0, `API недоступен: ${e instanceof Error ? e.message : String(e)}`);
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {}
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

const q = (params: Record<string, string | undefined>) => {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) sp.set(k, v);
  const s = sp.toString();
  return s ? `?${s}` : "";
};

export const api = {
  catalog: () => call<Catalog>("/api/catalog"),
  event: (slug: string) => call<EventT>(`/api/events/${encodeURIComponent(slug)}`),
  profile: (uid: number) => call<Profile>(`/api/profile/${uid}`),
  saveProfile: (uid: number, body: ProfilePatch) =>
    call<Profile>(`/api/profile/${uid}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  decisions: (uid: number) => call<Decision[]>(`/api/decisions/${uid}`),
  decide: (body: { user_id: number; event: string; status: string; reason?: string; day?: string }) =>
    call<Decision>("/api/decisions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  removeDecision: (uid: number, event: string) =>
    call<{ removed: boolean }>(`/api/decisions/${uid}/${encodeURIComponent(event)}`, { method: "DELETE" }),
  digest: (uid: number, today?: string) => call<Digest>(`/api/digest/${uid}/preview${q({ today })}`),
  digestAll: (uid: number, today?: string) => call<ScoredEvent[]>(`/api/digest/${uid}/all${q({ today })}`),
  plan: (uid: number, today?: string) => call<Plan>(`/api/plan/${uid}${q({ today })}`),
  ics: async (slug: string, day?: string) => {
    const res = await fetch(`${apiBase()}/api/events/${encodeURIComponent(slug)}/ics${q({ day })}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
      headers: { "X-API-Key": apiKey() },
    });
    return res;
  },
};
