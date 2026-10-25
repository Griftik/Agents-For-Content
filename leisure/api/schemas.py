"""Схемы ответов и запросов API."""
from __future__ import annotations

import math
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from leisure.core.catalog import (ALL_CATS, AREA_OPTIONS, COMPANY_OPTIONS, DECISION_ALIASES, DECISION_STATUSES, KNOWN_TAGS, REASONS, SLOTS,
                                  VALUES)

AFFINITY_MAX = 100.0


class WhyOut(BaseModel):
    t: str
    c: str = ""


class LinksOut(BaseModel):
    gcal: str
    outlook: str
    ics: str
    tg: str
    page: str


class EventOut(BaseModel):
    id: str
    slug: str
    title: str
    category: str
    subcategory: str = ""
    kind: str
    city: str
    dates: list[str]
    time_text: str = ""
    start_time: str | None = None
    end_time: str | None = None
    duration_min: int | None = None
    venue: str = ""
    address: str = ""
    metro: str = ""
    price_from: int | None = None
    price_text: str = ""
    description: str = ""
    why_fit_hint: str = ""
    note: str = ""
    tags: list[str] = []
    aesthetics: int
    novelty: int
    crowd: str
    audience_30plus: bool
    audience_kids: bool
    url: str = ""
    rating: dict | None = None
    confidence: str
    status: str
    slot: str
    free: bool


class DecisionOut(BaseModel):
    event_id: str | None
    event_slug: str
    status: str
    reason: str | None
    day: str | None
    rating: int | None


class ScoredEventOut(EventOut):
    score: int
    why: list[WhyOut]
    links: LinksOut
    decision: DecisionOut | None = None   # текущее решение пользователя по событию или null


class ParamsIn(BaseModel):
    """Параметры профиля; передаются только меняемые ключи, лишние отклоняются."""

    model_config = ConfigDict(extra="forbid")

    aesthetics: bool | None = None
    adults30: bool | None = None
    kids: bool | None = None
    budget: int | None = Field(default=None, ge=0, le=1_000_000)
    company: str | None = None
    times: list[str] | None = Field(default=None, max_length=4)
    areas: list[str] | None = Field(default=None, max_length=12)
    travel_minutes: int | None = Field(default=None, ge=0, le=240)         # время в пути: на сегодня лента прячет старты раньше now + это (по умолчанию 40)
    interests_basis: list[str] | None = Field(default=None, max_length=5)   # служебное: пятёрка, от которой посчитаны интересы
    nudge_budget: bool | None = None                                         # служебное: подсказка про бюджет уже показана

    @field_validator("company")
    @classmethod
    def _company(cls, v):
        if v is not None and v not in COMPANY_OPTIONS:
            raise ValueError(f"company: одно из {COMPANY_OPTIONS}")
        return v

    @field_validator("times")
    @classmethod
    def _times(cls, v):
        if v is not None and (bad := [t for t in v if t not in SLOTS]):
            raise ValueError(f"times: неизвестные слоты {bad}, допустимы {SLOTS}")
        return list(dict.fromkeys(v)) if v is not None else v

    @field_validator("areas")
    @classmethod
    def _areas(cls, v):
        if v is not None and (bad := [a for a in v if not (a in AREA_OPTIONS or 0 < len(a) <= 40)]):
            raise ValueError(f"areas: некорректные значения {bad}")
        return v


class AffinityIn(BaseModel):
    """Ручная правка «Что я узнал о тебе»: желаемые веса по указанным тегам и категориям (остальные не трогаем).
    Формат совпадает с `affinity` из GET профиля, поэтому его можно вернуть как есть (поле `n` игнорируется)."""

    model_config = ConfigDict(extra="forbid")

    tag: dict[str, float] = {}
    cat: dict[str, float] = {}
    n: int | None = None

    @field_validator("tag")
    @classmethod
    def _tags(cls, v):
        if bad := [k for k in v if k not in KNOWN_TAGS]:
            raise ValueError(f"affinity.tag: неизвестные теги {bad}")
        return cls._weights(v, "tag")

    @field_validator("cat")
    @classmethod
    def _cats(cls, v):
        if bad := [k for k in v if k not in ALL_CATS]:
            raise ValueError(f"affinity.cat: неизвестные категории {bad}")
        return cls._weights(v, "cat")

    @staticmethod
    def _weights(v: dict[str, float], name: str) -> dict[str, float]:
        for k, w in v.items():
            if not math.isfinite(w) or abs(w) > AFFINITY_MAX:
                raise ValueError(f"affinity.{name}: вес {k} должен быть числом от -{AFFINITY_MAX} до {AFFINITY_MAX}")
        return v


class ProfileIn(BaseModel):
    """Частичное обновление: передаются только меняемые поля."""

    name: str | None = Field(default=None, max_length=200)
    username: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=80)
    values: dict[str, int] | None = None
    interests: dict[str, int] | None = None
    params: ParamsIn | None = None
    notes: str | None = Field(default=None, max_length=2000)
    affinity: AffinityIn | None = None    # ручная правка «Что я узнал о тебе»; пересчёт по решениям её не затирает
    tz: str | None = Field(default=None, max_length=64)
    digest_day: int | None = Field(default=None, ge=1, le=7)
    digest_hour: int | None = Field(default=None, ge=0, le=23)
    ref_code: str | None = Field(default=None, max_length=8, description="код рекомендации/приглашения из start_param: новому человеку ставит source и referred_by")
    show_name: bool | None = None         # показывать ли имя друзьям (приглашения)
    can_write: bool | None = None         # человек разрешил push (веб ставит после диалога разрешения)
    offer_seen: int | None = Field(default=None, ge=0, le=2)   # предложение своей подборки приглашённому: 0 / 1 («Потом») / 2 (повтор показан)
    consent: bool | None = None
    onboarded: bool | None = None  # бот ставит в конце онбординга; иначе считаем по шагу «интересы»

    @field_validator("values")
    @classmethod
    def _values(cls, v):
        if v is None:
            return v
        for k, w in v.items():
            if k not in VALUES:
                raise ValueError(f"values: неизвестная ценность «{k}»")
            if not 0 <= int(w) <= 5:
                raise ValueError(f"values: вес {k} должен быть 0–5")
        return v

    @field_validator("interests")
    @classmethod
    def _interests(cls, v):
        if v is None:
            return v
        for k, w in v.items():
            if not 0 < len(k) <= 80:
                raise ValueError("interests: имя категории до 80 символов")
            if not 0 <= int(w) <= 3:
                raise ValueError(f"interests: интерес к «{k}» должен быть 0–3")
        return v

    @field_validator("tz")
    @classmethod
    def _tz(cls, v):
        if v is not None:
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
            try:
                ZoneInfo(v)
            except (ZoneInfoNotFoundError, ValueError):
                raise ValueError(f"tz: неизвестная зона «{v}»")
        return v


class ProfileOut(BaseModel):
    user_id: int
    account_id: int = 0               # аккаунт (версия 2): у основного профиля равен user_id
    kind: str = "self"                # self | parent | child | other
    name: str
    username: str
    city: str
    values: dict[str, int]
    interests: dict[str, int]
    params: dict[str, Any]
    notes: str
    tz: str
    digest_day: int
    digest_hour: int
    plan: str
    affinity: dict
    learned: dict
    learned_text: str
    onboarded: bool
    show_name: bool = True
    can_write: bool = True
    offer_seen: int = 0
    email: str | None = None          # почта аккаунта (вход на другом устройстве) или null
    offer_due: str | None = None      # YYYY-MM-DD: когда повторить предложение онбординга приглашённому (день события + 1) или null
    has_consent: bool = False         # согласие на обработку данных дано: веб зовёт /open только при нём
    source: str = "organic"
    affinity_manual_at: str | None = None   # когда пользователь последний раз правил affinity вручную


class DecisionIn(BaseModel):
    user_id: int
    event: str = Field(description="uuid или slug события", max_length=120)
    status: str
    reason: str | None = None
    day: date | None = None
    rating: int | None = Field(default=None, ge=1, le=5)

    @field_validator("status")
    @classmethod
    def _status(cls, v):
        v = DECISION_ALIASES.get(v, v)          # going/maybe/not_mine/went/skipped → русские статусы
        if v not in DECISION_STATUSES:
            raise ValueError(f"status должен быть одним из {DECISION_STATUSES}")
        return v

    @field_validator("reason")
    @classmethod
    def _reason(cls, v):
        if v is not None and v not in REASONS + ["не хочется"]:
            raise ValueError(f"reason должен быть одним из {REASONS}")
        return v


class DigestItemOut(BaseModel):
    event: EventOut
    day: str | None
    slot: str
    score: int | None
    why: list[WhyOut]
    chosen: bool = False
    links: LinksOut
    days: list[str] = []                  # дни уикенда, на которые есть событие
    decision: DecisionOut | None = None   # текущее решение пользователя по событию или null


class DigestOut(BaseModel):
    user_id: int
    weekend: list[str]
    title: str
    items: list[DigestItemOut]
    horizon: list[DigestItemOut]


class PlanItemOut(BaseModel):
    event: EventOut
    status: str                     # иду | может | сходил | не сходил
    day: str
    rating: int | None = None       # оценка 1–5 (после «сходил»)
    conflict: bool = False
    companions: list[str] = []      # с кем идёт по приглашениям («вдвоём с Имя»); скрытое имя — «другом»
    links: LinksOut


class PlanOut(BaseModel):
    weekend: list[str]              # окно плана: 7 дней от сегодня (имя поля историческое)
    today: str
    title: str
    days: dict[str, list[PlanItemOut]]
    horizon: list[PlanItemOut]      # «иду»/«может» дальше недели
    past: list[PlanItemOut]         # прошедшие (до 30 дней): для отметок «сходил / не сходил» и оценки, новые сверху
    text: str


class InviteCreateIn(BaseModel):
    user_id: int | None = None          # из сессии Mini App; можно передать заголовком X-User-Id
    event_slug: str | None = Field(default=None, description="slug (или uuid) события; для kind=ref не нужен", max_length=120)
    day: date | None = None
    kind: str = Field(default="event", pattern="^(event|ref)$")


class InviteCreatedOut(BaseModel):
    code: str
    kind: str
    url: str                            # <WEB_BASE_URL>/e/<slug>?inv=<код> (рекомендация — <WEB_BASE_URL>/?ref=<код>)
    web_url: str                        # то же, что url (оставлено для совместимости)
    share_text: str                     # от первого лица, со ссылкой: для «Поделиться» и «Скопировать»


class InviteOut(BaseModel):
    code: str
    kind: str
    event: DigestItemOut | None         # карточка как в дайджесте (без оценки); null, если событие удалено
    day: str | None
    event_slug: str | None = None       # slug события (есть и когда событие снято: страница покажет «событие убрали»)
    inviter_name: str | None            # null, если пригласивший скрыл имя (show_name)
    is_own: bool = False                # приглашение создал тот, кто спрашивает (?user_id=): T-INVITE-SELF
    status: str                         # active | past | unpublished | gone
    accepted: int
    my_status: str | None = None        # для ?user_id=: opened | going | maybe | declined
    score: int | None = None            # «Совпадение N %» под профиль спросившего (как в дайджесте); null, если профиль не настроен
    why: list[WhyOut] | None = None     # «Почему тебе»; null вместе со score


class InviteOpenIn(BaseModel):
    user_id: int | None = None
    name: str = Field(default="", max_length=200)
    username: str = Field(default="", max_length=100)


class InviteAcceptIn(InviteOpenIn):
    status: str = Field(pattern="^(going|maybe|declined)$")      # declined — «Другие выходные под меня»: запись без решения
    consent: bool = False               # согласие на обработку данных при первом касании (когда профиля или согласия нет)


class InviteAcceptOut(BaseModel):
    decision: DecisionOut | None        # null для status=declined
    together_with: str | None           # имя пригласившего (если не скрыто)
    profile_state: str                  # new | onboarded


class CatalogOut(BaseModel):
    values: list[str]
    categories: list[str]
    business_categories: list[str]
    tags: list[str]
    reasons: list[str]
    company: list[str]
    areas: list[str]
    times: list[str]
    default_profile: dict
    category_values: dict[str, dict[str, float]] = {}
    proposed_n: int = 8
    proposed_top: int = 5
    value_clusters: dict[str, list[str]] = {}
    value_short: dict[str, str] = {}


# ─── продукт без Telegram (docs/PIVOT-PWA.md, версия 2): гостевая сессия, профили аккаунта, лента, вход по почте ───
class SessionOut(BaseModel):
    user_id: int                      # идентификатор гостя = id аккаунта = user_id основного профиля; профиль создаётся первым PUT /api/profile с consent


class ProfileCreateIn(BaseModel):
    user_id: int | None = None        # любой профиль аккаунта (обычно основной); можно заголовком X-User-Id
    name: str = Field(min_length=1, max_length=200)
    kind: str = Field(default="other", pattern="^(self|parent|child|other)$")


class ProfileSummaryOut(BaseModel):
    user_id: int
    name: str
    kind: str
    onboarded: bool
    is_main: bool                     # user_id == id аккаунта


class ProfilesOut(BaseModel):
    account_id: int
    email: str | None
    profiles: list[ProfileSummaryOut]


class FeedItemOut(BaseModel):
    event: EventOut
    day: str                          # первый день окна, на который успеваешь
    days: list[str]                   # все подходящие дни окна
    score: int
    why: list[WhyOut]                 # для «что я о тебе узнал»; в ленте v2 не показывается
    can_make_it: bool                 # на сегодня: старт не раньше now + travel_minutes
    links: LinksOut
    decision: DecisionOut | None = None


class FeedOut(BaseModel):
    user_id: int
    date: str                         # как запросили: today | tomorrow | week | YYYY-MM-DD
    days: list[str]                   # дни окна
    today: str
    segment: str
    travel_minutes: int
    items: list[FeedItemOut]


class EmailAuthIn(BaseModel):
    user_id: int | None = None
    email: str = Field(max_length=254)


class EmailAuthOut(BaseModel):
    user_id: int                      # аккаунт (его основной профиль), к которому веб привязывает сессию
    account_id: int
    email: str
    moved: bool                       # true — почта уже была у другого аккаунта, сессию нужно перенести на него


class RefAskOut(BaseModel):
    url: str                          # ссылка-рекомендация на веб
    share_text: str                   # от первого лица, со ссылкой (T-REF-SHARE)


class DecisionPostOut(DecisionOut):
    ref_ask: RefAskOut | None = None  # оценка 4–5 и не чаще раза в 14 дней: показать экран рекомендации
    ask_reason: bool = False          # оценка 1–2: спросить, что было не так (причины как у «Мимо»)
