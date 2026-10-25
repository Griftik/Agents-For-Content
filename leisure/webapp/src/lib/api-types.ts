// Типы ответов API (зеркало leisure/api/schemas.py).

export type Why = { t: string; c: string };
export type Links = { gcal: string; outlook: string; ics: string; tg: string; page: string };

export type EventT = {
  id: string;
  slug: string;
  title: string;
  category: string;
  subcategory: string;
  kind: string;
  city: string;
  dates: string[];
  time_text: string;
  start_time: string | null;
  end_time: string | null;
  duration_min: number | null;
  venue: string;
  address: string;
  metro: string;
  price_from: number | null;
  price_text: string;
  description: string;
  why_fit_hint: string;
  note: string;
  tags: string[];
  aesthetics: number;
  novelty: number;
  crowd: string;
  url: string;
  rating: Record<string, unknown> | null;
  confidence: string;
  slot: string;
  free: boolean;
};
export type ScoredEvent = EventT & { score: number; why: Why[] };
export type DigestItem = { event: EventT; day: string | null; slot: string; score: number | null; why: Why[]; chosen: boolean; links: Links };
export type Digest = { user_id: number; weekend: string[]; title: string; items: DigestItem[]; horizon: DigestItem[] };
export type PlanItem = { event: EventT; status: string; day: string; rating?: number | null; conflict: boolean; links: Links; companions?: string[] };
/** GET /api/plan/{id}: weekend — окно из 7 дат от сегодня (имя историческое), past — прошедшие за 30 дней для отметок и оценки. */
export type Plan = { weekend: string[]; today?: string; title: string; days: Record<string, PlanItem[]>; horizon: PlanItem[]; past?: PlanItem[]; text: string };
export type Decision = { event_id: string | null; event_slug: string; status: string; reason: string | null; day: string | null; rating: number | null };
export type Learned = { likes?: unknown[]; dislikes?: unknown[]; reasons?: Record<string, number>; n?: number } & Record<string, unknown>;
export type Profile = {
  user_id: number;
  name: string;
  username: string;
  city: string;
  values: Record<string, number>;
  interests: Record<string, number>;
  params: {
    aesthetics?: boolean;
    adults30?: boolean;
    kids?: boolean;
    budget?: number;
    company?: string;
    times?: string[];
    areas?: string[];
    travel_minutes?: number;
  } & Record<string, unknown>;
  notes: string;
  tz: string;
  digest_day: number;
  digest_hour: number;
  plan: string;
  learned: Learned;
  learned_text: string;
  onboarded: boolean;
  /** Показывать имя друзьям в приглашениях (по умолчанию true). */
  show_name?: boolean;
  source?: string;
  /** Предложение своей подборки приглашённому: 0 не показывали, 1 «Потом», 2 повтор показан. */
  offer_seen?: number;
  /** Ручная правка «что я о тебе узнал» и накопленные веса: {tag: {…}, cat: {…}, n}. */
  affinity?: { tag?: Record<string, number>; cat?: Record<string, number>; n?: number };
  /** Время на дорогу, мин (для «успеваешь»); по умолчанию 40. */
  travel_minutes?: number;
  /** Вид профиля в аккаунте: self | parent | child | other. */
  kind?: string;
  /** Аккаунт (у основного профиля равен user_id). */
  account_id?: number;
  /** Привязанная почта аккаунта или null. */
  email?: string | null;
  /** YYYY-MM-DD: когда повторить предложение онбординга приглашённому (день события + 1) или null. */
  offer_due?: string | null;
  /** Согласие на обработку данных дано (профиль-заготовка без согласия — false). */
  has_consent?: boolean;
};
export type Catalog = {
  values: string[];
  categories: string[];
  business_categories?: string[];
  reasons: string[];
  company: string[];
  areas: string[];
  times: string[];
  /** Группы ценностей для экрана онбординга: «Познание» → [...]. */
  value_clusters?: Record<string, string[]>;
  /** Короткие подписи ценностей на кнопках. */
  value_short?: Record<string, string>;
  /** Таблица «направление → ценности» (вес 0–1) для подбора восьми направлений; пока бэкенд её не отдаёт (см. README). */
  category_values?: Record<string, Record<string, number>>;
};
export type ProfilePatch = Partial<Pick<Profile, "notes" | "values" | "interests">> & {
  params?: Profile["params"];
  /** Правка «что я о тебе узнал»: желаемые веса по тегам и категориям (как в GET профиля, поле n игнорируется). */
  affinity?: { tag?: Record<string, number>; cat?: Record<string, number> };
  name?: string;
  username?: string;
  show_name?: boolean;
  offer_seen?: number;
  consent?: boolean;
  onboarded?: boolean;
  /** Код рекомендации `ref_<код>` из start_param: передаётся при первом касании (имя поля согласуется с бэкендом). */
  ref_code?: string;
};

// ─── Приглашения (leisure/docs/GROWTH.md, раздел 6; зеркало InviteOut / InviteCreatedOut / InviteAcceptOut из api/schemas.py) ───
export type InviteStatus = "active" | "past" | "unpublished" | "gone";
/** POST /api/invites. Ссылка приглашения — web_url (адрес приложения); url оставлен для совместимости и может быть null. */
export type InviteCreated = { code: string; kind: string; url: string | null; web_url: string; share_text: string };
/** GET /api/invites/{code}. event — карточка как в дайджесте; null, если событие удалено (status = gone). */
export type InviteView = {
  code: string;
  kind: string;
  event: DigestItem | null;
  day: string | null;
  /** Слаг события есть и у снятого с публикации: страница покажет «событие убрали». */
  event_slug: string | null;
  inviter_name: string | null;
  /** Приглашение создал тот, кто спрашивает (?user_id=): «Это твоё приглашение». */
  is_own: boolean;
  status: InviteStatus;
  accepted: number;
  my_status: string | null;
  /** Для ?user_id= с настроенным профилем: совпадение 0–100 и причины (те же, что на карточке дайджеста); иначе null. */
  score: number | null;
  why: Why[] | null;
};
export type InviteAcceptStatus = "going" | "maybe" | "declined";
/** POST /api/invites/{code}/accept. Для declined решения нет. */
export type InviteAccepted = { decision: Decision | null; together_with: string | null; profile_state: "new" | "onboarded" };

// ─── Приложение (docs/PIVOT-PWA.md): гостевая сессия ───
/** Гостевая сессия: POST /api/session. */
export type SessionCreated = { user_id: number; token?: string };

// ─── Лента и профили аккаунта (API v2, leisure/README.md «Продукт без Telegram») ───
/** Элемент GET /api/feed: day — первый день окна, на который успеваешь; can_make_it — на сегодня старт не раньше now + travel_minutes. */
export type FeedItem = {
  event: EventT;
  day: string;
  days: string[];
  score: number;
  why: Why[];
  can_make_it: boolean;
  links: Links;
  decision?: Decision | null;
  /** Обложки в модели события пока нет; поле на будущее. */
  cover?: string | null;
};
export type Feed = { user_id: number; date: string; days: string[]; today: string; segment: string; travel_minutes: number; items: FeedItem[] };
/** Профиль аккаунта в переключателе («я», «мама», «ребёнок»). */
export type AccountProfile = { user_id: number; name: string; kind: "self" | "parent" | "child" | "other" | string; onboarded: boolean; is_main: boolean };
export type AccountProfiles = { account_id: number; email: string | null; profiles: AccountProfile[] };
