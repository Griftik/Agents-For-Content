import "server-only";
import { apiBase, apiKey } from "./config";
import type { AccountProfiles, Catalog, Feed, SessionCreated, Decision, Digest, EventT, InviteAcceptStatus, InviteAccepted, InviteCreated, InviteView, Plan, Profile, ProfilePatch, ScoredEvent } from "./api-types";
import { MockError, mockCall, mockEnabled } from "./mock";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

const TIMEOUT_MS = 8000;

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  if (mockEnabled()) {
    try {
      return mockCall(path, init) as T;
    } catch (e) {
      if (e instanceof MockError) throw new ApiError(e.status, e.message);
      throw e;
    }
  }
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
  const text = await res.text();
  return (text ? JSON.parse(text) : {}) as T;
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
  decide: (body: { user_id: number; event: string; status: string; reason?: string; day?: string; rating?: number }) =>
    call<Decision>("/api/decisions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  removeDecision: (uid: number, event: string) =>
    call<{ removed: boolean }>(`/api/decisions/${uid}/${encodeURIComponent(event)}`, { method: "DELETE" }),
  digest: (uid: number, today?: string) => call<Digest>(`/api/digest/${uid}/preview${q({ today })}`),
  digestAll: (uid: number, today?: string) => call<ScoredEvent[]>(`/api/digest/${uid}/all${q({ today })}`),
  plan: (uid: number, today?: string) => call<Plan>(`/api/plan/${uid}${q({ today })}`),
  /** POST /api/session: гостевой аккаунт с первого экрана (user_id; подпись cookie ставит веб). */
  createSession: () => call<SessionCreated>("/api/session", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }),
  /** GET /api/feed: лента на день или неделю по направлению, ранжированная под профиль. */
  feed: (profileId: number, date: string, segment: string, limit = 20) =>
    call<Feed>(`/api/feed${q({ user_id: String(profileId), date, segment, limit: String(limit) })}`),
  /** GET /api/profiles?user_id=: все профили аккаунта по id любого из них. */
  profiles: (uid: number) => call<AccountProfiles>(`/api/profiles${q({ user_id: String(uid) })}`),
  /** POST /api/profiles: новый профиль в аккаунте («мама», «ребёнок»); ответ — обновлённый список. */
  createProfile: (uid: number, name: string, kind: string) =>
    call<AccountProfiles>("/api/profiles", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ user_id: uid, name, kind }) }),
  /** POST /api/auth/email: ссылка-вход на почту; 503, пока у API нет SMTP. */
  linkEmail: (uid: number, email: string) =>
    call<unknown>("/api/auth/email", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ user_id: uid, email }) }),
  /** «Удалить мои данные»: профиль, решения, подписки. */
  deleteProfile: (uid: number) => call<unknown>(`/api/profile/${uid}`, { method: "DELETE" }),
  /** GET /api/invites/{code}; user_id (необязательно) нужен, чтобы автор узнал своё приглашение (is_own) и my_status. */
  invite: (code: string, uid?: number) => call<InviteView>(`/api/invites/${encodeURIComponent(code)}${q({ user_id: uid ? String(uid) : undefined })}`),
  /** POST /api/invites: код и ссылка для события и дня (повторный вызов возвращает то же приглашение). */
  createInvite: (uid: number, slug: string, day: string | null) =>
    call<InviteCreated>("/api/invites", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ user_id: uid, event_slug: slug, day: day ?? undefined }) }),
  /** POST /api/invites kind=ref: ссылка-рекомендация сервиса (момент рекомендации после оценки 4–5). */
  createReferral: (uid: number) =>
    call<InviteCreated>("/api/invites", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ user_id: uid, kind: "ref" }) }),
  /** POST /api/invites/{code}/accept; consent=true при первом касании; name — необязательное имя с формы. */
  acceptInvite: (code: string, body: { user_id: number; status: InviteAcceptStatus; consent: boolean; name?: string }) =>
    call<InviteAccepted>(`/api/invites/${encodeURIComponent(code)}/accept`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  /** POST /api/invites/{code}/open: первый вход по ссылке; для ref-кода ставит source=ref и referred_by новому человеку. */
  openInvite: (code: string, body: { user_id: number; name?: string }) =>
    call<InviteView>(`/api/invites/${encodeURIComponent(code)}/open`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  ics: async (slug: string, day?: string) => {
    const res = await fetch(`${apiBase()}/api/events/${encodeURIComponent(slug)}/ics${q({ day })}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
      headers: { "X-API-Key": apiKey() },
    });
    return res;
  },
};
