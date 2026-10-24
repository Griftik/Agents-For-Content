"""Схемы ответов и запросов API."""
from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from leisure.core.catalog import AREA_OPTIONS, COMPANY_OPTIONS, DECISION_STATUSES, REASONS, SLOTS, VALUES


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


class ScoredEventOut(EventOut):
    score: int
    why: list[WhyOut]


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


class ProfileIn(BaseModel):
    """Частичное обновление: передаются только меняемые поля."""

    name: str | None = Field(default=None, max_length=200)
    username: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=80)
    values: dict[str, int] | None = None
    interests: dict[str, int] | None = None
    params: ParamsIn | None = None
    notes: str | None = Field(default=None, max_length=2000)
    tz: str | None = Field(default=None, max_length=64)
    digest_day: int | None = Field(default=None, ge=1, le=7)
    digest_hour: int | None = Field(default=None, ge=0, le=23)
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
        if v not in DECISION_STATUSES:
            raise ValueError(f"status должен быть одним из {DECISION_STATUSES}")
        return v

    @field_validator("reason")
    @classmethod
    def _reason(cls, v):
        if v is not None and v not in REASONS + ["не хочется"]:
            raise ValueError(f"reason должен быть одним из {REASONS}")
        return v


class DecisionOut(BaseModel):
    event_id: str | None
    event_slug: str
    status: str
    reason: str | None
    day: str | None
    rating: int | None


class DigestItemOut(BaseModel):
    event: EventOut
    day: str | None
    slot: str
    score: int | None
    why: list[WhyOut]
    chosen: bool = False
    links: LinksOut


class DigestOut(BaseModel):
    user_id: int
    weekend: list[str]
    title: str
    items: list[DigestItemOut]
    horizon: list[DigestItemOut]


class PlanItemOut(BaseModel):
    event: EventOut
    status: str
    day: str
    conflict: bool = False
    links: LinksOut


class PlanOut(BaseModel):
    weekend: list[str]
    title: str
    days: dict[str, list[PlanItemOut]]
    horizon: list[PlanItemOut]
    text: str


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
    value_clusters: dict[str, list[str]] = {}
    value_short: dict[str, str] = {}
