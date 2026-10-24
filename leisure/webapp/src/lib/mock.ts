// Мок-режим MOCK_INVITES=1: экраны приглашений можно смотреть и проверять без бэкенда.
// Работает только при NODE_ENV=development (npm run dev) и test (vitest); в production-сборке и в `next start` игнорируется.
// Подставляется на уровне api.ts: все вызовы страниц остаются прежними, ответы приходят из памяти процесса.
import type { Catalog, Decision, Digest, DigestItem, EventT, Plan, PlanItem, Profile } from "./api-types";

export const mockEnabled = () => process.env.MOCK_INVITES === "1" && process.env.NODE_ENV !== "production";

export class MockError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

const WEEKEND = ["2026-10-23", "2026-10-24", "2026-10-25"];

const event = (o: Partial<EventT> & Pick<EventT, "slug" | "title" | "dates">): EventT => ({
  id: `id-${o.slug}`, category: "Своими руками", subcategory: "", kind: "workshop", city: "Москва", time_text: "", start_time: "13:00",
  end_time: "15:00", duration_min: 120, venue: "Ателье ГЭС-2", address: "Болотная наб., 15", metro: "Полянка", price_from: 2500, price_text: "от 2 500 ₽",
  description: "Мастер-класс: вырезать деревянного духа-хранителя. Материалы включены.", why_fit_hint: "Вырезаешь сам, мастер рядом.", note: "", tags: [],
  aesthetics: 4, novelty: 3, crowd: "малая", url: "https://example.com/event", rating: null, confidence: "подтверждено", slot: "день", free: false, ...o,
});

export const MOCK_EVENTS: EventT[] = [
  event({ slug: "karmannyj-ongon", title: "Карманный онгон: вырезать деревянного духа-хранителя", dates: ["2026-10-24"] }),
  event({ slug: "dzhaz-na-kryshe", title: "Джаз на крыше", category: "Джаз", dates: ["2026-10-23"], start_time: "20:00", end_time: "22:00", venue: "Крыша Vol. 2", metro: "Таганская", price_from: 1200, price_text: "от 1 200 ₽", why_fit_hint: "Живая музыка, камерный зал.", slot: "вечер" }),
  event({ slug: "usadba-progulka", title: "Прогулка по усадьбе Кусково", category: "Природа и усадьбы", dates: ["2026-10-25"], start_time: "12:00", end_time: "14:00", venue: "Усадьба Кусково", metro: "Выхино", price_from: 0, price_text: "бесплатно", free: true, why_fit_hint: "Осенний парк и неспешная экскурсия." }),
  event({ slug: "stary-spektakl", title: "Спектакль, который уже прошёл", category: "Театр", dates: ["2026-10-10"], venue: "Малый театр" }),
];
const bySlug = (s: string) => MOCK_EVENTS.find((e) => e.slug === s || e.id === s);

/** Коды приглашений для просмотра экранов: открой `/e/<slug>?inv=<код>`. */
export const MOCK_CODES: Record<string, { slug: string; day: string; name: string | null; status: string; inviter: number }> = {
  MOCKOK01: { slug: "karmannyj-ongon", day: "2026-10-24", name: "Алина", status: "active", inviter: 9001 },
  MOCKANON: { slug: "dzhaz-na-kryshe", day: "2026-10-23", name: null, status: "active", inviter: 9002 },
  MOCKPAST: { slug: "stary-spektakl", day: "2026-10-10", name: "Алина", status: "past", inviter: 9001 },
  MOCKUNPB: { slug: "usadba-progulka", day: "2026-10-25", name: "Алина", status: "unpublished", inviter: 9001 },
  MOCKGONE: { slug: "karmannyj-ongon", day: "2026-10-24", name: null, status: "gone", inviter: 0 }, // пригласивший удалил профиль, событие доступно
};

const CATEGORIES = ["Джаз", "Концерты", "Театр", "Современное искусство", "Кино", "Винные бары", "Вечеринки", "Своими руками", "Природа и усадьбы", "Волейбол", "Волейбол: матчи", "ИИ и технологии", "Управление и стратегия", "Предприниматели и клубы", "Нетривиальное"];
const VALUES = ["Творчество", "Наставничество", "Забота", "Единство/Дружба", "Развитие", "Красота/эстетика", "Инновации/новизна", "Свобода", "Семья", "Исследования", "Здоровье", "Сохранение традиций", "Природа", "Удовольствие", "Веселье", "Азарт", "Покой", "Близость", "Смысл"];

export const MOCK_CATALOG: Catalog = {
  values: VALUES,
  categories: CATEGORIES,
  business_categories: ["Конференции и форумы", "Бизнес-завтраки", "Закрытые клубы", "Образование для управленцев"],
  reasons: ["не моё", "дорого", "далеко", "уже был", "не в это время", "не та компания"],
  company: ["любая", "один", "вдвоём", "с друзьями", "с семьёй"],
  areas: ["любой", "центр", "север", "юг"],
  times: ["день", "вечер"],
  value_clusters: {
    "Познание": ["Развитие", "Исследования", "Инновации/новизна", "Творчество"],
    "Люди": ["Единство/Дружба", "Наставничество", "Забота", "Семья", "Близость"],
    "Тело и чувства": ["Здоровье", "Красота/эстетика", "Природа", "Удовольствие", "Покой", "Азарт", "Веселье"],
    "Смысл": ["Свобода", "Сохранение традиций", "Смысл"],
  },
  value_short: { "Красота/эстетика": "Эстетика", "Единство/Дружба": "Дружба", "Инновации/новизна": "Новизна", "Сохранение традиций": "Традиции" },
  category_values: {
    "Джаз": { "Творчество": .8, "Красота/эстетика": .6, "Единство/Дружба": .5, "Свобода": .7, "Веселье": .3, "Удовольствие": .4 },
    "Концерты": { "Красота/эстетика": .8, "Творчество": .6, "Удовольствие": .6, "Веселье": .4 },
    "Театр": { "Красота/эстетика": .9, "Смысл": .7, "Творчество": .6, "Исследования": .5, "Сохранение традиций": .5 },
    "Современное искусство": { "Творчество": .9, "Красота/эстетика": .8, "Инновации/новизна": .8, "Исследования": .6, "Смысл": .4 },
    "Кино": { "Творчество": .6, "Красота/эстетика": .6, "Смысл": .5, "Исследования": .4, "Удовольствие": .3, "Близость": .3 },
    "Винные бары": { "Удовольствие": .9, "Единство/Дружба": .6, "Красота/эстетика": .5, "Близость": .5, "Веселье": .3 },
    "Вечеринки": { "Веселье": .9, "Единство/Дружба": .8, "Свобода": .6, "Удовольствие": .4, "Инновации/новизна": .4 },
    "Своими руками": { "Творчество": .9, "Развитие": .5, "Семья": .5, "Покой": .4, "Наставничество": .3 },
    "Природа и усадьбы": { "Природа": .9, "Сохранение традиций": .7, "Покой": .6, "Красота/эстетика": .5, "Семья": .5, "Здоровье": .4 },
    "Волейбол": { "Здоровье": .9, "Единство/Дружба": .6, "Азарт": .6, "Природа": .2 },
    "Волейбол: матчи": { "Азарт": .9, "Единство/Дружба": .6, "Веселье": .4, "Здоровье": .3 },
    "ИИ и технологии": { "Инновации/новизна": .9, "Развитие": .8, "Исследования": .8 },
    "Управление и стратегия": { "Развитие": .9, "Наставничество": .6, "Инновации/новизна": .4 },
    "Предприниматели и клубы": { "Единство/Дружба": .7, "Наставничество": .7, "Развитие": .6, "Свобода": .4, "Инновации/новизна": .4 },
    "Нетривиальное": { "Исследования": .9, "Смысл": .6, "Развитие": .6, "Инновации/новизна": .6, "Творчество": .3 },
  },
};

type Store = {
  profiles: Map<number, Profile>;
  decisions: Map<number, Decision[]>;
  invites: Map<string, { slug: string; day: string; inviter: number }>;
  together: Map<string, string>; // "<uid>:<slug>" → имя пригласившего
};
const g = globalThis as unknown as { __leisureMock?: Store };
export function store(): Store {
  if (!g.__leisureMock) {
    const s: Store = { profiles: new Map(), decisions: new Map(), invites: new Map(), together: new Map() };
    // 1001 — готовый профиль; 1002 — заготовка без онбординга; 9001 — «Алина» (пригласившая); остальные id профиля не имеют.
    s.profiles.set(1001, profile(1001, "Мария", true));
    s.profiles.set(9001, profile(9001, "Алина", true));
    s.profiles.set(1002, profile(1002, "Игорь", false)); // профиль-заготовка: согласие есть, подборку не настраивал
    g.__leisureMock = s;
  }
  return g.__leisureMock;
}
export const resetMock = () => {
  g.__leisureMock = undefined;
};

function profile(uid: number, name: string, onboarded: boolean): Profile {
  return {
    user_id: uid, name, username: "", city: "Москва", values: Object.fromEntries(VALUES.map((v, i) => [v, i < 5 ? 5 : 2])),
    interests: Object.fromEntries(CATEGORIES.map((c) => [c, 2])), params: { budget: 0, company: "любая", times: ["день", "вечер"], areas: ["любой"] },
    notes: "", tz: "Europe/Moscow", digest_day: 4, digest_hour: 18, plan: "", learned: {}, learned_text: "", onboarded, show_name: true, source: "organic",
    has_consent: true, offer_seen: 0, offer_due: null, can_write: false,
  };
}

const links = (e: EventT, day: string) => ({
  gcal: `https://calendar.google.com/calendar/render?action=TEMPLATE&text=${encodeURIComponent(e.title)}&dates=${day.replace(/-/g, "")}`,
  outlook: `https://outlook.live.com/calendar/0/deeplink/compose?subject=${encodeURIComponent(e.title)}&startdt=${day}`,
  ics: `/api/events/${e.slug}/ics?day=${day}`, tg: "https://t.me/share/url", page: `/e/${e.slug}`,
});

function planOf(uid: number): Plan {
  const st = store();
  const days: Record<string, PlanItem[]> = Object.fromEntries(WEEKEND.map((d) => [d, []]));
  const horizon: PlanItem[] = [];
  for (const d of st.decisions.get(uid) ?? []) {
    if (d.status !== "иду" && d.status !== "может") continue;
    const e = bySlug(d.event_slug);
    if (!e) continue;
    const day = d.day ?? e.dates[0];
    const who = st.together.get(`${uid}:${e.slug}`);
    const item: PlanItem = { event: e, status: d.status, day, conflict: false, links: links(e, day), companions: who ? [who] : [] };
    (days[day] ??= []).push(item);
  }
  return { weekend: WEEKEND, title: "23–25 октября", days, horizon, text: "План (мок)" };
}

const j = (init: RequestInit) => (init.body ? JSON.parse(String(init.body)) : {});

/** Маршрутизатор мока: тот же путь и метод, что у настоящего API. */
export function mockCall(path: string, init: RequestInit = {}): unknown {
  const method = (init.method ?? "GET").toUpperCase();
  const url = new URL(path, "http://mock");
  const p = url.pathname;
  const st = store();
  let m: RegExpExecArray | null;

  if (p === "/api/catalog") return MOCK_CATALOG;

  if ((m = /^\/api\/events\/([^/]+)$/.exec(p))) {
    const e = bySlug(decodeURIComponent(m[1]));
    if (!e) throw new MockError(404, "событие не найдено");
    return e;
  }

  if ((m = /^\/api\/profile\/(\d+)$/.exec(p))) {
    const uid = Number(m[1]);
    if (method === "PUT") {
      const b = j(init);
      const cur = st.profiles.get(uid) ?? { ...profile(uid, b.name ?? "", false), has_consent: false };
      const next: Profile = {
        ...cur,
        name: b.name ?? cur.name,
        values: { ...cur.values, ...(b.values ?? {}) },
        interests: { ...cur.interests, ...(b.interests ?? {}) },
        params: { ...cur.params, ...(b.params ?? {}) },
        notes: b.notes ?? cur.notes,
        show_name: b.show_name ?? cur.show_name,
        onboarded: cur.onboarded || b.onboarded === true || b.interests !== undefined,
        source: b.ref_code ? "ref" : cur.source,
        has_consent: cur.has_consent || b.consent === true,
        offer_seen: b.offer_seen ?? cur.offer_seen,
        can_write: b.can_write ?? cur.can_write,
      };
      st.profiles.set(uid, next);
      return next;
    }
    const prof = st.profiles.get(uid);
    if (!prof) throw new MockError(404, "профиль не найден");
    return prof;
  }

  if ((m = /^\/api\/decisions\/(\d+)$/.exec(p))) return st.decisions.get(Number(m[1])) ?? [];
  if (p === "/api/decisions" && method === "POST") {
    const b = j(init);
    const e = bySlug(b.event);
    if (!e) throw new MockError(404, "событие не найдено");
    const list = (st.decisions.get(b.user_id) ?? []).filter((d) => d.event_slug !== e.slug);
    const d: Decision = { event_id: e.id, event_slug: e.slug, status: b.status, reason: b.reason ?? null, day: b.day ?? e.dates[0], rating: null };
    st.decisions.set(b.user_id, [...list, d]);
    return d;
  }
  if ((m = /^\/api\/decisions\/(\d+)\/([^/]+)$/.exec(p)) && method === "DELETE") {
    const uid = Number(m[1]);
    const slug = decodeURIComponent(m[2]);
    st.decisions.set(uid, (st.decisions.get(uid) ?? []).filter((d) => d.event_slug !== slug));
    return { removed: true };
  }

  if ((m = /^\/api\/digest\/(\d+)\/(preview|all)$/.exec(p))) {
    const uid = Number(m[1]);
    const evs = MOCK_EVENTS.filter((e) => e.dates.some((d) => WEEKEND.includes(d)));
    if (m[2] === "all") return evs.map((e, i) => ({ ...e, score: 90 - i * 7, why: [{ t: "Творчество", c: "" }] }));
    const items: DigestItem[] = evs.map((e, i) => {
      const day = e.dates[0];
      const chosen = (st.decisions.get(uid) ?? []).some((d) => d.event_slug === e.slug && d.status === "иду");
      return { event: e, day, slot: e.slot, score: 90 - i * 7, why: [{ t: "Творчество", c: "" }], chosen, links: links(e, day) };
    });
    const digest: Digest = { user_id: uid, weekend: WEEKEND, title: "23–25 октября", items, horizon: [] };
    return digest;
  }
  if ((m = /^\/api\/plan\/(\d+)$/.exec(p))) return planOf(Number(m[1]));

  if (p === "/api/invites" && method === "POST") {
    const b = j(init);
    const e = bySlug(b.event_slug ?? b.event);
    if (!e) throw new MockError(404, "событие не найдено");
    if (!st.profiles.has(b.user_id)) throw new MockError(404, "профиль пригласившего не найден");
    const day = b.day ?? e.dates[0];
    const code = `MOCK${(b.user_id % 10000).toString().padStart(4, "0")}`;
    st.invites.set(code, { slug: e.slug, day, inviter: b.user_id });
    return { code, kind: "event", url: `https://t.me/mock_bot/app?startapp=inv_${code}`, web_url: `http://localhost:3000/e/${e.slug}?inv=${code}`, share_text: `Иду на «${e.title.slice(0, 59)}»: ${day}. ${e.why_fit_hint}\nПойдёшь со мной? https://t.me/mock_bot/app?startapp=inv_${code}` };
  }

  if ((m = /^\/api\/invites\/([A-Za-z0-9]+)\/open$/.exec(p)) && method === "POST") {
    // Без согласия профиль не создаётся, открытие только считается; ref-код человеку с согласием ставит source=ref.
    const b = j(init);
    const prof = st.profiles.get(b.user_id);
    if (prof?.has_consent && m[1].startsWith("REF") && prof.source === "organic") st.profiles.set(b.user_id, { ...prof, source: "ref" });
    return { code: m[1], kind: m[1].startsWith("REF") ? "ref" : "event", event: null, day: null, event_slug: null, inviter_name: null, is_own: false, status: "active", accepted: 0, my_status: null, score: null, why: null };
  }

  if ((m = /^\/api\/invites\/([A-Za-z0-9]+)(\/accept)?$/.exec(p))) {
    const code = m[1];
    const known = MOCK_CODES[code] ?? (() => {
      const own = st.invites.get(code);
      return own ? { slug: own.slug, day: own.day, name: st.profiles.get(own.inviter)?.name ?? null, status: "active", inviter: own.inviter } : undefined;
    })();
    if (!known) throw new MockError(404, "приглашение не найдено");
    const e = bySlug(known.slug) ?? null;
    if (!m[2]) {
      const viewer = Number(url.searchParams.get("user_id")) || 0;
      const item: DigestItem | null = e ? { event: e, day: known.day, slot: e.slot, score: null, why: [], chosen: false, links: links(e, known.day) } : null;
      const ready = !!viewer && !!st.profiles.get(viewer)?.onboarded;
      const why = ready ? [{ t: "Творчество", c: "" }, { t: "Руками", c: "learn" }] : null;
      if (item && ready) Object.assign(item, { score: 84, why: why! });
      return {
        code, kind: "event", event: item, day: known.day, event_slug: known.slug, inviter_name: known.name, is_own: !!viewer && viewer === known.inviter,
        status: known.status, accepted: 0, my_status: null, score: ready ? 84 : null, why,
      };
    }
    // accept
    const b = j(init);
    if (known.status !== "active" && known.status !== "gone") throw new MockError(410, known.status);
    const uid = Number(b.user_id);
    if (uid === known.inviter) throw new MockError(400, "своё приглашение принять нельзя");
    let prof = st.profiles.get(uid);
    if (!prof) {
      if (b.consent !== true && b.status !== "declined") throw new MockError(409, "consent_required");
      prof = profile(uid, b.name ?? "", false);
      prof.source = "invite";
      prof.has_consent = b.consent === true;
      if (b.status === "declined") return { decision: null, together_with: null, profile_state: "new" };
      st.profiles.set(uid, prof);
    }
    if (!prof.has_consent && b.status !== "declined") {
      if (b.consent !== true) throw new MockError(409, "consent_required");
      prof.has_consent = true;
    }
    const state: "new" | "onboarded" = prof.onboarded ? "onboarded" : "new";
    if (b.status === "declined") return { decision: null, together_with: null, profile_state: state };
    const status = b.status === "going" ? "иду" : "может";
    const d: Decision = { event_id: e?.id ?? null, event_slug: known.slug, status, reason: null, day: known.day, rating: null };
    st.decisions.set(uid, [...(st.decisions.get(uid) ?? []).filter((x) => x.event_slug !== known.slug), d]);
    if (status === "иду" && known.name) st.together.set(`${uid}:${known.slug}`, known.name);
    if (!prof.offer_due) {
      const d = new Date(`${known.day}T00:00:00Z`);
      d.setUTCDate(d.getUTCDate() + 1);
      prof.offer_due = d.toISOString().slice(0, 10); // повтор предложения: день события + 1
    }
    return { decision: d, together_with: status === "иду" ? known.name : null, profile_state: state };
  }

  throw new MockError(404, `мок: нет маршрута ${method} ${p}`);
}
