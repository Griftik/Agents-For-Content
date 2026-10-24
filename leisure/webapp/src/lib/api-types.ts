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
export type PlanItem = { event: EventT; status: string; day: string; conflict: boolean; links: Links };
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
};
export type Catalog = {
  values: string[];
  categories: string[];
  reasons: string[];
  company: string[];
  areas: string[];
  times: string[];
};
export type ProfilePatch = Partial<Pick<Profile, "notes" | "values" | "interests">> & { params?: Profile["params"] };
