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
export type PlanItem = { event: EventT; status: string; day: string; conflict: boolean; links: Links; companions?: string[] };
export type Plan = { weekend: string[]; title: string; days: Record<string, PlanItem[]>; horizon: PlanItem[]; text: string };
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
  /** Бот может писать человеку (профиль из Mini App — false до requestWriteAccess или /start). */
  can_write?: boolean;
  /** Предложение своей подборки приглашённому: 0 не показывали, 1 «Потом», 2 повтор показан. */
  offer_seen?: number;
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
  name?: string;
  username?: string;
  show_name?: boolean;
  can_write?: boolean;
  offer_seen?: number;
  consent?: boolean;
  onboarded?: boolean;
  /** Код рекомендации `ref_<код>` из start_param: передаётся при первом касании (имя поля согласуется с бэкендом). */
  ref_code?: string;
};

// ─── Приглашения (leisure/docs/GROWTH.md, раздел 6; зеркало InviteOut / InviteCreatedOut / InviteAcceptOut из api/schemas.py) ───
export type InviteStatus = "active" | "past" | "unpublished" | "gone";
/** POST /api/invites. url = null, пока в API не заданы бот и MINIAPP_SHORT_NAME: тогда share_text содержит web_url. */
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
