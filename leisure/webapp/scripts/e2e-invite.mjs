// Сквозная проверка приглашений без браузера: настоящий FastAPI + Next в dev (без MOCK_INVITES), запросы curl-образные (fetch).
// Путь: пригласивший «Иду» → «Позвать друга» → друг открывает ?inv= → «Иду» без галочки → с галочкой → в плане пригласившего «вдвоём».
// Запуск (API на :8000 и Next dev на :3111 уже подняты, см. README): node scripts/e2e-invite.mjs
import { createHmac } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const API = process.env.E2E_API ?? "http://localhost:8000";
const WEB = process.env.E2E_WEB ?? "http://localhost:3111";
const KEY = process.env.API_KEY ?? "e2e-key";
const SECRET = process.env.SESSION_SECRET ?? "e2e-secret";
const SLUG = process.env.E2E_EVENT ?? "rock-symphony-queen-muse-prove-2026-10-25";
const DAY = process.env.E2E_DAY ?? "2026-10-25";
const INVITER = 880001;
const FRIEND = 880002;

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const actions = (() => {
  const m = JSON.parse(readFileSync(resolve(root, ".next/server/server-reference-manifest.json"), "utf8")).node;
  const out = {};
  for (const [id, v] of Object.entries(m)) for (const w of Object.values(v.workers)) {
    const hit = new RegExp(`${id}%22%2C%22exportedName%22%3A%22(\\w+)%22`).exec(w.moduleId);
    if (hit) out[hit[1]] = id;
  }
  return out;
})();

const session = (uid) => {
  const exp = Math.floor(Date.now() / 1000) + 3600;
  const body = `${uid}.${exp}`;
  return `leisure_session=${body}.${createHmac("sha256", SECRET).update(body).digest("base64url")}`;
};
const who = (name) => `leisure_who=${Buffer.from(JSON.stringify({ n: name, u: "" })).toString("base64url")}`;
const cookie = (uid, name) => [session(uid), name ? who(name) : ""].filter(Boolean).join("; ");

const api = async (path, init = {}) => {
  const r = await fetch(API + path, { ...init, headers: { "X-API-Key": KEY, "Content-Type": "application/json", ...(init.headers ?? {}) } });
  return { status: r.status, body: await r.json().catch(() => null) };
};
const page = async (path, ck) => {
  const r = await fetch(WEB + path, { headers: ck ? { cookie: ck } : {}, redirect: "manual" });
  return { status: r.status, text: (await r.text()).replace(/<script[\s\S]*?<\/script>/g, "").replace(/<[^>]*>/g, " ").replace(/\s+/g, " ") };
};
/** Вызов server action: простые аргументы — JSON-массивом, FormData — multipart с ссылкой $K1 (формат React Flight). */
const act = async (name, args, ck, form, multi) => {
  const headers = { "Next-Action": actions[name], Accept: "text/x-component", cookie: ck, Origin: WEB };
  let body;
  if (form !== undefined) {
    body = new FormData();
    for (const [k, v] of Object.entries(form ?? {})) body.append(`_1_${k}`, v);
    for (const [k, vs] of Object.entries(multi ?? {})) for (const v of vs) body.append(`_1_${k}`, v);
    body.set("0", JSON.stringify([...args, "$K1"])); // поля вложенного FormData называются _1_<имя>, ссылка $K1 идёт после них (как у encodeReply в React 19)
  } else {
    headers["Content-Type"] = "text/plain;charset=UTF-8";
    body = JSON.stringify(args);
  }
  const r = await fetch(`${WEB}/e/${SLUG}`, { method: "POST", headers, body, redirect: "manual" });
  return { status: r.status, text: await r.text(), redirect: r.headers.get("x-action-redirect") };
};

let failed = 0;
const check = (ok, what, extra = "") => {
  console.log(`${ok ? "OK  " : "FAIL"} ${what}${extra ? ` — ${extra}` : ""}`);
  if (!ok) failed++;
};

// 0. пригласивший: профиль и «Иду» (то, что делает карточка в /digest)
await api(`/api/profile/${INVITER}`, { method: "PUT", body: JSON.stringify({ name: "Алина Тестова", consent: true, onboarded: true, show_name: true }) });
await api(`/api/decisions/${INVITER}/${SLUG}`, { method: "DELETE" });
const dec = await api("/api/decisions", { method: "POST", body: JSON.stringify({ user_id: INVITER, event: SLUG, status: "иду", day: DAY }) });
check(dec.status === 200, "пригласивший отметил «Иду»", `HTTP ${dec.status}`);
await api(`/api/profile/${FRIEND}`, { method: "DELETE" }).catch(() => {});

// 1. «Позвать друга»: server action → POST /api/invites
const created = await act("createInviteAction", [SLUG, DAY], cookie(INVITER, "Алина Тестова"));
const code = /"code":"([A-Z0-9]{8})"/.exec(created.text)?.[1];
const shareText = /"shareText":"((?:[^"\\]|\\.)*)"/.exec(created.text)?.[1];
check(!!code, "createInviteAction вернул код", code);
check(!!shareText && shareText.includes("Пойдёшь со мной?"), "share_text от первого лица со ссылкой", JSON.stringify(shareText?.slice(-70)));

// 2. страница приглашения
const guest = await page(`/e/${SLUG}?inv=${code}`);
check(guest.text.includes("Алина зовёт тебя") && guest.text.includes("Открыть в Telegram"), "браузер без Telegram: шапка «Алина зовёт тебя» и «Открыть в Telegram»");
const friendPage = await page(`/e/${SLUG}?inv=${code}`, cookie(FRIEND, "Борис Друг"));
check(friendPage.text.includes("Алина зовёт тебя") && friendPage.text.includes("Даю согласие") && friendPage.text.includes("Иду вместе"), "друг без профиля: шапка, галочка согласия, «Иду вместе»");
const own = await page(`/e/${SLUG}?inv=${code}`, cookie(INVITER));
check(own.text.includes("Это твоё приглашение"), "автор видит «Это твоё приглашение»");
const bad = await page(`/e/-?inv=ZZZZZZZZ`, cookie(FRIEND));
check(bad.text.includes("Эта ссылка не работает"), "неизвестный код: «Эта ссылка не работает»");

// 3. «Иду вместе»: без согласия → просьба галочки; с согласием → записано
const form = { code, slug: SLUG, day: DAY, status: "going", needs_consent: "1" };
const noConsent = await act("acceptInviteAction", [{ phase: "idle" }], cookie(FRIEND, "Борис Друг"), form);
check(noConsent.text.includes('"error":"consent"'), "без галочки запись не идёт (consent)");
const accepted = await act("acceptInviteAction", [{ phase: "idle" }], cookie(FRIEND, "Борис Друг"), { ...form, consent: "on" });
check(accepted.text.includes('"phase":"done"') && accepted.text.includes('"togetherWith":"Алина"'), "с галочкой: «Вы идёте вместе», вместе с Алина", accepted.text.match(/"profileState":"\w+"/)?.[0]);
check(/"ics":"\/api\/events\/[^"]+\/ics\?day=2026-10-25"/.test(accepted.text), "в ответе есть ссылки календарей");

const withConsent = await page(`/e/${SLUG}?inv=${code}`, cookie(FRIEND, "Борис Друг"));
check(withConsent.text.includes("Иду вместе") && !withConsent.text.includes("Даю согласие"), "у друга с согласием (has_consent) галочки нет");
const friendProfile = (await api(`/api/profile/${FRIEND}`)).body;
const nextDay = new Date(Date.parse(`${DAY}T00:00:00Z`) + 86400_000).toISOString().slice(0, 10);
check(friendProfile.has_consent === true && friendProfile.offer_due === nextDay, "профиль друга: has_consent, offer_due = день события + 1", `${friendProfile.has_consent} ${friendProfile.offer_due}`);

// 4. у пригласившего в плане «вдвоём»
const plan = await api(`/api/plan/${INVITER}?today=2026-10-24`);
const item = Object.values(plan.body?.days ?? {}).flat().concat(plan.body?.horizon ?? []).find((x) => x.event.slug === SLUG);
check(item?.companions?.includes("Борис"), "API: в плане пригласившего companions = [Борис]", JSON.stringify(item?.companions));
const web = await page("/plan?today=2026-10-25", cookie(INVITER));
check(web.text.includes("Вдвоём с Борис"), "веб /plan пригласившего: «Вдвоём с Борис»");
const friendPlan = await page("/plan?today=2026-10-25", cookie(FRIEND));
check(friendPlan.text.includes("Вдвоём с Алина"), "веб /plan друга: «Вдвоём с Алина»");

// 5. повтор, «Другие выходные под меня», профиль, метрики
const again = await act("acceptInviteAction", [{ phase: "idle" }], cookie(FRIEND, "Борис Друг"), { ...form, needs_consent: "", status: "maybe" });
check(again.text.includes('"phase":"done"'), "повторное принятие («может быть») проходит без галочки");
const decl = await act("declineInviteAction", [], cookie(FRIEND), { code });
check(decl.redirect === "/digest" || /onboarding|digest/.test(decl.redirect ?? ""), "declineInviteAction редиректит", decl.redirect ?? decl.status);
const prof = await api(`/api/profile/${FRIEND}`);
check(prof.body?.source === "invite", "профиль друга создан с source=invite", prof.body?.source);
const sw = await act("setShowNameAction", [false], cookie(INVITER));
check((await api(`/api/profile/${INVITER}`)).body?.show_name === false, "переключатель имени: PUT show_name=false дошёл до API", sw.status);
await act("setShowNameAction", [true], cookie(INVITER));
const hidden = await api(`/api/invites/${code}`);
check(hidden.body?.inviter_name === "Алина", "после включения имя снова отдаётся");

// 5а. открытие и отказ без согласия не создают профиль
const STRANGER = 880004;
await api(`/api/profile/${STRANGER}`, { method: "DELETE" }).catch(() => {});
await act("openInviteAction", [code], cookie(STRANGER, "Пётр Гость"));
check((await api(`/api/profile/${STRANGER}`)).status === 404, "/open без согласия профиль не создаёт");
const strangerDecl = await act("declineInviteAction", [], cookie(STRANGER, "Пётр Гость"), { code });
check(strangerDecl.redirect?.startsWith("/profile?onboarding=welcome") && (await api(`/api/profile/${STRANGER}`)).status === 404, "declined без согласия: переход в онбординг, профиля нет", strangerDecl.redirect);

// 6. онбординг в два шага (друг после «Давай»)
const FRIEND_CK = cookie(FRIEND, "Борис Друг");
const catalog = (await api("/api/catalog")).body;
const top = ["Творчество", "Красота/эстетика", "Инновации/новизна", "Исследования", "Смысл"];
const step1 = await act("saveOnboardingValuesAction", [], FRIEND_CK, {}, { top });
check(step1.redirect?.startsWith("/profile?onboarding=2"), "шаг 1 из 2: пять ценностей записаны, переход на шаг 2", step1.redirect);
const mid = (await api(`/api/profile/${FRIEND}`)).body;
check(Object.values(mid.values).filter((w) => w === 5).length === 5 && mid.onboarded === false, "после шага 1 вес 5 у пяти ценностей, профиль ещё не готов");
const step2 = await page("/profile?onboarding=2", FRIEND_CK);
check(step2.text.includes("Шаг 2 из 2") && step2.text.includes("Показать подборку"), "страница шага 2 из 2: направления и бюджет");
const fin = await act("finishOnboardingAction", [], FRIEND_CK, { budget: "2500" }, { cat: ["Театр", "Джаз"] });
check(fin.redirect?.startsWith("/digest"), "шаг 2 из 2: «Показать подборку» ведёт в /digest", fin.redirect ?? fin.status);
const done = (await api(`/api/profile/${FRIEND}`)).body;
check(done.onboarded === true && done.params.budget === 2500, "профиль готов, бюджет 2500", `onboarded=${done.onboarded} budget=${done.params?.budget}`);
const matched = await page(`/e/${SLUG}?inv=${code}`, FRIEND_CK);
check(/Совпадение \d+ %/.test(matched.text) && matched.text.includes("Почему тебе"), "друг с готовым профилем видит «Совпадение N %» и «Почему тебе»", matched.text.match(/Совпадение \d+ %/)?.[0]);
check(catalog.categories.length > 8 && Object.keys(done.interests).length >= 8, "интересы записаны по всем направлениям");
check(Boolean(catalog.category_values), "каталог отдаёт category_values (иначе восемь направлений по текущим интересам)", catalog.category_values ? "да" : "нет, запасной вариант");

// 7. рекомендация ref_: код → cookie → первое касание профиля
const ref = await api("/api/invites", { method: "POST", body: JSON.stringify({ user_id: INVITER, kind: "ref" }) });
await api("/api/profile/880003", { method: "DELETE" }).catch(() => {});
const refPost = await fetch(`${WEB}/api/ref`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code: ref.body.code }) });
check(refPost.ok && /leisure_ref=/.test(refPost.headers.get("set-cookie") ?? ""), "/api/ref кладёт код в cookie", ref.body.code);
const start = await act("startOnboardingAction", [], `${cookie(880003, "Вера Новая")}; leisure_ref=${ref.body.code}`, { consent: "on", needs_consent: "1" });
check(start.redirect?.startsWith("/profile?onboarding=1"), "приветствие → «Начать» → шаг 1", start.redirect);
const refProf = (await api("/api/profile/880003")).body;
check(refProf?.source === "ref", "новый профиль получил source=ref по коду рекомендации", refProf?.source);

console.log(failed ? `\n${failed} проверок не прошли` : "\nвсе проверки прошли");
process.exit(failed ? 1 : 0);
