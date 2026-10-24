import type { Decision, EventT, InviteAccepted, InviteCreated, InviteStatus, InviteView } from "./api-types";
import { buildShareText, miniAppLink } from "./invite-share";

/**
 * Приведение ответов API приглашений к контракту GROWTH §6.
 * Бэкенд на момент написания (api/schemas.py: InviteOut) отдаёт немного другое: `state` (ok / event_gone / past) вместо `status`,
 * `companions[]` вместо `together_with`, `web_link`/`bot_link` вместо `url`/`web_url` и без `share_text`. Адаптер принимает обе формы,
 * чтобы веб не ломался при любом из вариантов; расхождения перечислены в README («Что ждём от бэкенда»).
 */

type Raw = Record<string, unknown>;
const obj = (v: unknown): Raw => (v && typeof v === "object" ? (v as Raw) : {});
const str = (v: unknown): string | null => (typeof v === "string" && v ? v : null);

const STATE_TO_STATUS: Record<string, InviteStatus> = { ok: "active", event_gone: "unpublished", past: "past", gone: "gone" };
const STATUSES: InviteStatus[] = ["active", "past", "unpublished", "gone"];

export function toInviteView(rawIn: unknown): InviteView {
  const r = obj(rawIn);
  const s = str(r.status);
  const st = str(r.state);
  const status: InviteStatus = s && (STATUSES as string[]).includes(s) ? (s as InviteStatus) : st && STATE_TO_STATUS[st] ? STATE_TO_STATUS[st] : "active";
  return {
    event: r.event && typeof r.event === "object" ? (r.event as EventT) : null,
    day: str(r.day),
    inviter_name: str(r.inviter_name),
    status,
    accepted: typeof r.accepted === "number" ? r.accepted : 0,
    inviter_is_me: r.inviter_is_me === true,
  };
}

export function toInviteCreated(rawIn: unknown, ctx: { event: Pick<EventT, "title" | "venue" | "why_fit_hint" | "start_time" | "end_time"> | null; day: string | null; bot: string; app: string }): InviteCreated {
  const r = obj(rawIn);
  const code = str(r.code) ?? "";
  const given = str(r.url);
  // Ссылка Mini App обязана быть вида startapp=inv_<код>; бэкенд пока отдаёт ?start=inv_ (чат с ботом), такую заменяем.
  const url = given && given.includes("startapp=") ? given : (miniAppLink(ctx.bot, ctx.app, "inv", code) ?? given ?? str(r.bot_link) ?? "");
  return {
    code,
    url,
    web_url: str(r.web_url) ?? str(r.web_link) ?? "",
    share_text: str(r.share_text) ?? (ctx.event ? buildShareText(ctx.event, ctx.day, url) : url),
  };
}

export function toInviteAccepted(rawIn: unknown, fallbackState: "new" | "onboarded"): InviteAccepted {
  const r = obj(rawIn);
  const companions = Array.isArray(r.companions) ? (r.companions as unknown[]).filter((x): x is string => typeof x === "string") : [];
  const ps = str(r.profile_state);
  return {
    decision: r.decision as Decision,
    together_with: str(r.together_with) ?? companions[0] ?? null,
    profile_state: ps === "new" || ps === "onboarded" ? ps : fallbackState,
  };
}
