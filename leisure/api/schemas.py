"""Схемы ответов и запросов API."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from leisure.core.catalog import DECISION_STATUSES


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


class ProfileIn(BaseModel):
    """Частичное обновление: передаются только меняемые поля."""

    name: str | None = None
    username: str | None = None
    city: str | None = None
    values: dict[str, int] | None = None
    interests: dict[str, int] | None = None
    params: dict[str, Any] | None = None
    notes: str | None = None
    tz: str | None = None
    digest_day: int | None = Field(default=None, ge=1, le=7)
    digest_hour: int | None = Field(default=None, ge=0, le=23)
    consent: bool | None = None


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
    event: str = Field(description="uuid или slug события")
    status: str
    reason: str | None = None
    day: str | None = None
    rating: int | None = Field(default=None, ge=1, le=5)

    def check(self) -> None:
        if self.status not in DECISION_STATUSES:
            raise ValueError(f"status должен быть одним из {DECISION_STATUSES}")


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
