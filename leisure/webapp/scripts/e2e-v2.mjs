// Сквозная проверка версии 2 без браузера: настоящий FastAPI (LEISURE_DEV_OPEN_API=1) + production-сборка веба без мока.
// Путь: сессия → согласие → онбординг → лента сегодня / завтра / неделя и «Дело» → «Иду» / «Не моё» → план → «сходил» + оценка 5 →
// ref_ask → второй профиль с другими ценностями и другая лента → приглашение по ссылке → «Иду вместе» без сессии → companions
// у пригласившего → почта 503. Server actions вызываются теми же запросами, что шлёт браузер (Next-Action из манифеста сборки).
// Запуск (из корня репозитория и leisure/webapp):
//   LEISURE_DEV_OPEN_API=1 WEB_BASE_URL=http://localhost:3111 .venv/bin/uvicorn leisure.api.main:app --port 8000 &
//   npm run build && API_BASE_URL=http://localhost:8000 SESSION_SECRET=e2e-secret WEB_BASE_URL=http://localhost:3111 npx next start -p 3111 &
//   node scripts/e2e-v2.mjs   (cookie сессии выдаёт сам веб через POST /api/session, секрет скрипту не нужен)
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const API = process.env.E2E_API ?? "http://localhost:8000";
const WEB = process.env.E2E_WEB ?? "http://localhost:3111";
const KEY = process.env.API_KEY ?? "";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
/** Ид server actions из манифеста сборки (dev и production): "<id>":{…,"exportedName":"<имя>"} в server-reference-manifest.js. */
const actions = (() => {
  const raw = readFileSync(resolve(root, ".next/server/server-reference-manifest.js"), "utf8");
  const out = {};
  for (const m of raw.matchAll(/\\"([0-9a-f]{42})\\":\{\\"workers\\":\{.*?\},\\"filename\\":\\"[^\\]*\\",\\"exportedName\\":\\"(\w+)\\"/g)) out[m[2]] = m[1];
  if (!Object.keys(out).length) throw new Error("не нашёл server actions в .next: сначала npm run build");
  return out;
})();

const api = async (path, init = {}) => {
  const r = await fetch(API + path, { ...init, headers: { ...(KEY ? { "X-API-Key": KEY } : {}), "Content-Type": "application/json", ...(init.headers ?? {}) } });
  return { status: r.status, body: await r.json().catch(() => null) };
};
const page = async (path, ck) => {
  const r = await fetch(WEB + path, { headers: ck ? { cookie: ck } : {}, redirect: "manual" });
  const html = await r.text();
  return { status: r.status, location: r.headers.get("location"), html, text: html.replace(/<script[\s\S]*?<\/script>/g, "").replace(/<[^>]*>/g, " ").replace(/\s+/g, " ") };
};
/** Server action: аргументы JSON-массивом; FormData — multipart с полями `_1_<имя>` и ссылкой $K1 (как encodeReply в React 19). */
const act = async (name, args, ck, form, multi) => {
  const headers = { "Next-Action": actions[name], Accept: "text/x-component", cookie: ck ?? "", Origin: WEB };
  let body;
  if (form !== undefined) {
    body = new FormData();
    for (const [k, v] of Object.entries(form ?? {})) body.append(`_1_${k}`, v);
    for (const [k, vs] of Object.entries(multi ?? {})) for (const v of vs) body.append(`_1_${k}`, v);
    body.set("0", JSON.stringify([...args, "$K1"]));
  } else {
    headers["Content-Type"] = "text/plain;charset=UTF-8";
    body = JSON.stringify(args);
  }
  const r = await fetch(`${WEB}/profile`, { method: "POST", headers, body, redirect: "manual" });
  return { status: r.status, text: await r.text(), redirect: r.headers.get("x-action-redirect"), setCookie: r.headers.get("set-cookie") ?? "" };
};
/** Строка результата action в ответе React Flight: `1:{…}`; после revalidatePath перед ней идёт перерисовка страницы, а текстовые
 * чанки (`10:T64b,…`) не заканчиваются переводом строки, поэтому ищем `1:{` и в середине строки. */
const parseRow = (text) => {
  const m = /(?:^|\n)1:([^\n]*)/.exec(text) ?? /1:(\{"[^\n]*)/.exec(text);
  if (!m) console.log("    (ответ action без строки 1:", text.slice(0, 200).replace(/\n/g, " "), ")");
  try {
    return m ? JSON.parse(m[1]) : null;
  } catch {
    console.log("    (не разобрал ответ action:", m[1].slice(0, 200), ")");
    return null;
  }
};

let failed = 0;
const check = (ok, what, extra = "") => {
  console.log(`${ok ? "OK  " : "FAIL"} ${what}${extra ? ` — ${extra}` : ""}`);
  if (!ok) failed++;
};
const cleanup = [];

try {
  // 1. гостевая сессия через веб
  const sess = await fetch(`${WEB}/api/session`, { method: "POST" });
  const sc = sess.headers.get("set-cookie") ?? "";
  const token = /leisure_session=([^;]+)/.exec(sc)?.[1];
  const uid = Number(token?.split(".")[0]);
  check(sess.ok && uid >= 1e12, "POST /api/session веба: cookie сессии на 180 дней, user_id ≥ 10^12", String(uid));
  check(/Max-Age=15552000/.test(sc), "срок cookie 180 дней");
  const CK = `leisure_session=${token}`;
  cleanup.push(() => api(`/api/profile/${uid}`, { method: "DELETE" }));
  const home = await page("/", CK);
  check(home.status === 307 && /onboarding=welcome/.test(home.location ?? ""), "/ без профиля ведёт на приветствие", home.location ?? String(home.status));
  check((await api(`/api/profile/${uid}`)).status === 404, "до согласия профиля в API нет");

  // 2. согласие и онбординг
  const start = await act("startOnboardingAction", [], CK, { consent: "on", needs_consent: "1", name: "Вера" });
  check(start.redirect?.startsWith("/profile?onboarding=1"), "«Начать» с галочкой: профиль создан, шаг 1", start.redirect);
  const prof0 = (await api(`/api/profile/${uid}`)).body;
  check(prof0?.has_consent === true && prof0.account_id === uid && prof0.kind === "self" && prof0.name === "Вера", "профиль: has_consent, account_id = user_id, kind self, имя", JSON.stringify([prof0?.has_consent, prof0?.account_id === uid, prof0?.kind]));
  const feed409 = await api(`/api/feed?user_id=${uid}&date=today`);
  check(feed409.status === 409, "лента до онбординга — 409 not_onboarded");
  const topMain = ["Творчество", "Красота/эстетика", "Инновации/новизна", "Исследования", "Смысл"];
  const s1 = await act("saveOnboardingValuesAction", [], CK, {}, { top: topMain });
  check(s1.redirect?.startsWith("/profile?onboarding=2"), "шаг 1 / 2: пять ценностей → шаг 2", s1.redirect);
  const s2page = await page("/profile?onboarding=2", CK);
  check(s2page.text.includes("Шаг 2 / 2") && s2page.text.includes("Показать рекомендации"), "страница шага 2 / 2");
  const s2 = await act("finishOnboardingAction", [], CK, { budget: "2500" }, { cat: ["Театр", "Джаз", "Современное искусство", "Кино", "Нетривиальное"] });
  check(s2.redirect?.startsWith("/digest"), "шаг 2 / 2 → лента", s2.redirect);
  const prof1 = (await api(`/api/profile/${uid}`)).body;
  check(prof1?.onboarded === true && prof1.params?.budget === 2500 && prof1.params?.travel_minutes === 40, "профиль готов: бюджет 2500, travel_minutes 40");

  // 3. лента: сегодня / завтра / неделя / Дело
  const feeds = {};
  for (const [label, q] of [["today", "date=today&segment=leisure"], ["tomorrow", "date=tomorrow&segment=leisure"], ["week", "date=week&segment=leisure"], ["biz", "date=week&segment=business"]]) {
    feeds[label] = (await api(`/api/feed?user_id=${uid}&${q}`)).body;
  }
  check(feeds.today?.items?.length > 0 && feeds.today.items.every((i) => i.day === feeds.today.today), "API: лента на сегодня не пуста, все на сегодня", `${feeds.today?.items?.length} событий`);
  check(feeds.week?.items?.length >= feeds.today.items.length && feeds.week.days.length === 7, "API: неделя — окно из 7 дней, не меньше сегодняшних");
  check(Array.isArray(feeds.biz?.items) && feeds.biz.items.every((i) => ["Конференции и форумы", "Бизнес-завтраки", "Закрытые клубы", "Образование для управленцев"].includes(i.event.category)), "API: «Дело» — только бизнес-категории", `${feeds.biz?.items?.length} событий`);
  const first = feeds.today.items[0];
  const webToday = await page("/digest?day=today&seg=leisure", CK);
  check(webToday.text.includes(first.event.title) && webToday.text.includes("1 / " + Math.min(20, feeds.today.items.length)) && webToday.text.includes("Иду") && webToday.text.includes("Не моё"), "веб: лента «Сегодня» показывает первую карточку API со счётчиком и кнопками", first.event.title.slice(0, 40));
  check(webToday.text.includes("Успеваешь") === first.can_make_it, "веб: бейдж «Успеваешь» совпадает с can_make_it");
  const webWeek = await page("/digest?day=week&seg=leisure", CK);
  check(webWeek.text.includes("Неделя") && webWeek.text.includes(feeds.week.items[0].event.title), "веб: «Неделя» показывает первую карточку недели");
  const webTomorrow = await page("/digest?day=tomorrow&seg=leisure", CK);
  check(webTomorrow.status === 200 && (feeds.tomorrow.items.length ? webTomorrow.text.includes(feeds.tomorrow.items[0].event.title) : webTomorrow.text.includes("На этот день всё")), "веб: «Завтра» — карточка или «На этот день всё»", `${feeds.tomorrow.items.length} событий`);
  const webBiz = await page("/digest?day=week&seg=business", CK);
  check(webBiz.status === 200 && (feeds.biz.items.length ? webBiz.text.includes(feeds.biz.items[0].event.title) : webBiz.text.includes("Пока ничего") && webBiz.text.includes("Всё")), "веб: «Дело» — карточка или «Пока ничего» с кнопкой «Всё»");

  // 4. «Иду» и «Не моё» с карточки
  const second = feeds.today.items[1] ?? feeds.week.items.find((i) => i.event.slug !== first.event.slug);
  const go = parseRow((await act("feedDecideAction", [first.event.slug, first.day, "иду"], CK)).text);
  check(go?.ok === true, "«Иду» записано", first.event.slug);
  const no = parseRow((await act("feedDecideAction", [second.event.slug, second.day, "не моё"], CK)).text);
  check(no?.ok === true, "«Не моё» записано", second.event.slug);
  const decs = (await api(`/api/decisions/${uid}`)).body ?? [];
  check(decs.some((d) => d.event_slug === first.event.slug && d.status === "иду") && decs.some((d) => d.event_slug === second.event.slug && d.status === "не моё"), "API: решения «иду» и «не моё»");
  const undo = parseRow((await act("undoDecisionAction", [second.event.slug], CK)).text);
  const feedUndo = (await api(`/api/feed?user_id=${uid}&date=week&segment=all`)).body;
  check(undo?.ok === true && feedUndo.items.some((i) => i.event.slug === second.event.slug), "«Отменить» снимает «не моё», событие снова в ленте");
  await act("feedDecideAction", [second.event.slug, second.day, "не моё"], CK);
  const feedAfter = (await api(`/api/feed?user_id=${uid}&date=week&segment=all`)).body;
  check(!feedAfter.items.some((i) => i.event.slug === second.event.slug), "«не моё» больше не показывается в ленте");
  const third = feeds.week.items.find((i) => ![first.event.slug, second.event.slug].includes(i.event.slug));
  if (third) {
    await act("feedDecideAction", [third.event.slug, third.day, "иду"], CK);
    const rm = await act("removeFromPlan", [], CK, { slug: third.event.slug });
    const decsRm = (await api(`/api/decisions/${uid}`)).body ?? [];
    check(rm.status === 200 && !decsRm.some((d) => d.event_slug === third.event.slug), "«Убрать» в плане снимает решение", third.event.slug);
  }
  const affBefore = Number(((await api(`/api/profile/${uid}`)).body?.affinity?.cat ?? {})[first.event.category] ?? 0);
  const more = parseRow((await act("tweakLearnedAction", ["cat", first.event.category, "more"], CK)).text);
  const affMore = Number(((await api(`/api/profile/${uid}`)).body?.affinity?.cat ?? {})[first.event.category] ?? 0);
  await act("tweakLearnedAction", ["cat", first.event.category, "reset"], CK);
  const affReset = Number(((await api(`/api/profile/${uid}`)).body?.affinity?.cat ?? {})[first.event.category] ?? 0);
  check(more?.ok === true && affMore === affBefore + 1 && affReset === 0, "«Что я о тебе узнал»: Больше → +1, Сбросить → 0 по категории", `${affBefore} → ${affMore} → ${affReset}`);
  const webProfile = await page("/profile", CK);
  check(webProfile.text.includes("Что я о тебе узнал") && webProfile.text.includes("Удалить мои данные"), "веб: профиль с блоками «узнал» и «Удалить мои данные»");

  // 5. план и прошедшее: «сходил» + оценка 5 → ref_ask
  const plan = (await api(`/api/plan/${uid}`)).body;
  const inPlan = Object.values(plan.days).flat().find((x) => x.event.slug === first.event.slug);
  check(!!inPlan && plan.weekend.length === 7 && plan.today === feeds.today.today, "API: план на 7 дней содержит «иду»");
  const webPlan = await page("/plan", CK);
  check(webPlan.text.includes(first.event.title) && webPlan.text.includes("Календарь"), "веб: план показывает событие с кнопками");
  const yday = new Date(Date.parse(plan.today) - 86400_000).toISOString().slice(0, 10);
  const pastFeed = (await api(`/api/feed?user_id=${uid}&date=${yday}&today=${yday}&segment=all`)).body;
  // не то же событие, что «иду» сегодня, и не идущее сегодня: одно решение на событие
  const pastEv = pastFeed?.items?.find((i) => ![first.event.slug, second.event.slug].includes(i.event.slug) && !i.event.dates.includes(feeds.today.today));
  check(!!pastEv, "есть событие на вчера (для отметки «сходил»)", pastEv?.event?.slug);
  if (pastEv) {
    const d0 = await api("/api/decisions", { method: "POST", body: JSON.stringify({ user_id: uid, event: pastEv.event.slug, status: "иду", day: yday }) });
    check(d0.status === 200, "вчерашнее «иду» записано (через API, как если бы вчера)", String(d0.status));
    const planPast = (await api(`/api/plan/${uid}`)).body;
    check(planPast.past?.some((x) => x.event.slug === pastEv.event.slug && x.status === "иду"), "API: план отдаёт past с неотмеченным «иду»");
    const webPlan2 = await page("/plan", CK);
    check(webPlan2.text.includes("Прошли") && webPlan2.text.includes("Сходил") && webPlan2.html.includes("bn-dot"), "веб: секция «Прошли», чипы и точка на вкладке");
    const future = feeds.tomorrow.items[0] ?? feeds.week.items.find((i) => i.day > feeds.today.today);
    if (future) {
      const early = parseRow((await act("markPastAction", [future.event.slug, true], CK)).text);
      check(early?.ok === false, "«сходил» раньше дня события — отказ (400 от API)", future.event.slug);
      await api(`/api/decisions/${uid}/${future.event.slug}`, { method: "DELETE" });
    }
    const went = parseRow((await act("markPastAction", [pastEv.event.slug, true, 5], CK)).text);
    check(went?.ok === true && !!went.refAsk?.shareText && /https?:\/\//.test(went.refAsk.url), "«Сходил» + оценка 5 → ref_ask с ссылкой", went?.refAsk?.url);
    const planRated = (await api(`/api/plan/${uid}`)).body;
    check(planRated.past?.some((x) => x.event.slug === pastEv.event.slug && x.status === "сходил" && x.rating === 5), "API: past со статусом «сходил» и rating 5");
    const webPlan3 = await page("/plan", CK);
    check(webPlan3.text.includes("● 5 ★") && !webPlan3.html.includes("bn-dot"), "веб: звезда выбрана, точка на вкладке погасла");
  }

  // 6. второй профиль с другими ценностями
  const before = (await api(`/api/profiles?user_id=${uid}`)).body;
  check(before?.account_id === uid && before.profiles?.length === 1 && before.profiles[0].is_main, "API: один профиль «я» в аккаунте");
  const cp = await act("createProfileAction", [], CK, { pname: "Мама", kind: "parent" });
  const pcookie = /leisure_profile=([^;]+)/.exec(cp.setCookie)?.[1];
  const after = (await api(`/api/profiles?user_id=${uid}`)).body;
  const mama = after?.profiles?.find((p) => p.name === "Мама");
  check(cp.redirect?.startsWith("/profile?onboarding=1") && !!pcookie && !!mama && pcookie.startsWith(`${mama.user_id}.${uid}.`), "новый профиль «Мама»: cookie профиля подписан, шаг 1 для него", cp.redirect);
  const CKM = `${CK}; leisure_profile=${pcookie}`;
  const step1m = await page("/profile?onboarding=1", CKM);
  check(step1m.text.includes("Что важно для Мама"), "шаг 1 для второго профиля подписан его именем");
  await act("saveOnboardingValuesAction", [], CKM, {}, { top: ["Природа", "Здоровье", "Семья", "Покой", "Сохранение традиций"] });
  await act("finishOnboardingAction", [], CKM, { budget: "1000" }, { cat: ["Природа и усадьбы", "Волейбол"] });
  const mamaProf = (await api(`/api/profile/${mama.user_id}`)).body;
  check(mamaProf?.onboarded === true && mamaProf.account_id === uid && mamaProf.kind === "parent" && mamaProf.values["Природа"] === 5 && mamaProf.values["Творчество"] === 2, "профиль «Мама»: свой онбординг, свои ценности, тот же аккаунт");
  const feedMama = (await api(`/api/feed?user_id=${mama.user_id}&date=week&segment=leisure`)).body;
  const topMainSlugs = feeds.week.items.slice(0, 5).map((i) => i.event.slug).join(",");
  const topMamaSlugs = feedMama.items.slice(0, 5).map((i) => i.event.slug).join(",");
  check(feedMama.items.length > 0 && topMainSlugs !== topMamaSlugs, "лента второго профиля отличается от основной (первые пять)", `${topMamaSlugs.slice(0, 60)}…`);
  const webMama = await page("/digest?day=week&seg=leisure", CKM);
  check(webMama.text.includes(feedMama.items[0].event.title) && webMama.text.includes("Мама"), "веб: лента под активным профилем «Мама», имя в шапке");
  const sw = await act("switchProfileAction", [uid], CKM);
  check(sw.redirect?.startsWith("/digest") && /leisure_profile=[^;]*\.[^;]*\.[^;]*/.test(sw.setCookie), "переключение обратно на «я»", sw.redirect);
  const bad = await act("switchProfileAction", [424242], CK);
  check(bad.redirect?.startsWith("/profile"), "чужой id профиля не переключает");

  // 7. приглашение: «Иду вместе» без сессии → companions у пригласившего
  const inv = parseRow((await act("createInviteAction", [first.event.slug, first.day], CK)).text);
  check(inv?.ok === true && /\/e\/.+\?inv=[A-Z0-9]{8}/.test(inv.url) && inv.shareText.includes(inv.url), "«Позвать друга»: код, обычная ссылка приложения, текст от первого лица", inv?.url);
  const invPath = new URL(inv.url).pathname + new URL(inv.url).search;
  const badInv = await page(`/e/${first.event.slug}?inv=BADCODE00`, CK);
  check(badInv.text.includes("Эта ссылка не работает") && badInv.text.includes("К событию"), "битый код на существующем событии: явный экран и «К событию»");
  const badRef = await page("/r/BADCODE00", CK);
  const tmpSess = await fetch(`${WEB}/api/session`, { method: "POST" });
  const tmpTok = /leisure_session=([^;]+)/.exec(tmpSess.headers.get("set-cookie") ?? "")?.[1];
  const badRefPage = await page("/profile?onboarding=welcome&bad_ref=1", `leisure_session=${tmpTok}`);
  check(badRef.status === 303 && /bad_ref=1/.test(badRef.location ?? "") && badRefPage.text.includes("Ссылка не работает"), "битая ссылка-рекомендация: приветствие с пометкой", badRef.location);
  const guest = await page(invPath);
  check(guest.status === 200 && guest.text.includes("Вера зовёт тебя") && guest.text.includes("Иду вместе") && guest.text.includes("Даю согласие"), "страница приглашения без сессии: шапка, галочка, «Иду вместе»");
  const fsess = await fetch(`${WEB}/api/session`, { method: "POST" });
  const ftoken = /leisure_session=([^;]+)/.exec(fsess.headers.get("set-cookie") ?? "")?.[1];
  const fuid = Number(ftoken?.split(".")[0]);
  const CKF = `leisure_session=${ftoken}`;
  cleanup.push(() => api(`/api/profile/${fuid}`, { method: "DELETE" }));
  const code = /inv=([A-Z0-9]+)/.exec(inv.url)[1];
  const form = { code, slug: first.event.slug, day: first.day, status: "going", needs_consent: "1", name: "Борис" };
  const noConsent = parseRow((await act("acceptInviteAction", [{ phase: "idle" }], CKF, form)).text);
  check(noConsent?.error === "consent", "без галочки не записывается");
  const accepted = parseRow((await act("acceptInviteAction", [{ phase: "idle" }], CKF, { ...form, consent: "on" })).text);
  check(accepted?.phase === "done" && accepted.togetherWith === "Вера" && accepted.profileState === "new", "«Иду вместе» с галочкой: «Вы идёте вместе», вместе с Вера, профиль новый", JSON.stringify([accepted?.phase, accepted?.togetherWith]));
  const fprof = (await api(`/api/profile/${fuid}`)).body;
  check(fprof?.has_consent === true && fprof.source === "invite" && fprof.name === "Борис", "профиль друга: согласие, source invite, имя с формы");
  const planMain = (await api(`/api/plan/${uid}`)).body;
  const together = Object.values(planMain.days).flat().find((x) => x.event.slug === first.event.slug);
  const invState = (await api(`/api/invites/${code}?user_id=${uid}`)).body;
  check(together?.companions?.includes("Борис"), "API: у пригласившего companions = [Борис]", `${JSON.stringify(together?.companions)}; accepted=${invState?.accepted}, status=${invState?.status}`);
  const webPlanMain = await page("/plan", CK);
  check(webPlanMain.text.includes("Вдвоём с Борис"), "веб: у пригласившего «Вдвоём с Борис»");
  const webPlanFriend = await page("/plan", CKF);
  check(webPlanFriend.text.includes("Вдвоём с Вера"), "веб: у друга «Вдвоём с Вера»");

  // 8. почта без SMTP — 503 → «подключится позже»
  const mail = parseRow((await act("linkEmailAction", [{ phase: "idle" }], CK, { email: "vera@example.com" })).text);
  check(mail?.phase === "later", "почта без SMTP: «почта пока не подключена»", JSON.stringify(mail));
  check((await api("/api/auth/email", { method: "POST", body: JSON.stringify({ user_id: uid, email: "vera@example.com" }) })).status === 503, "API: POST /api/auth/email → 503");

  // 9. «Удалить мои данные» у друга и у основного аккаунта (с профилем «Мама»)
  const delF = await act("deleteDataAction", [], CKF);
  check(delF.redirect?.startsWith("/?deleted=1") && /leisure_session=;/.test(delF.setCookie) && (await api(`/api/profile/${fuid}`)).status === 404, "«Удалить мои данные» у друга: профиль стёрт, сессия сброшена", delF.redirect);
  const delM = await act("deleteDataAction", [], CK);
  check(delM.redirect?.startsWith("/?deleted=1") && (await api(`/api/profile/${uid}`)).status === 404 && (await api(`/api/profile/${mama.user_id}`)).status === 404, "«Удалить мои данные» у основного: аккаунт и профиль «Мама» стёрты");
  const deletedPage = await page("/?deleted=1");
  check(deletedPage.text.includes("Данные удалены"), "экран «Данные удалены»");
} finally {
  for (const f of cleanup) await f().catch(() => {});
}
console.log(failed ? `\n${failed} проверок не прошли` : "\nвсе проверки прошли");
process.exit(failed ? 1 : 0);
