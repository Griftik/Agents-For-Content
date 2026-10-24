"""Схема события на входе (seed, подача организатора, LLM-нормализатор). Валидация pydantic (п. 7 спеки)."""
from __future__ import annotations

import re
from datetime import date, time
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from leisure.core.catalog import CONFIDENCE, CROWD, EVENT_STATUSES, KINDS, KNOWN_TAGS
from leisure.core.timeutil import end_hour, hhmm, start_hour

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,119}$")


class RatingIn(BaseModel):
    source: str = ""
    value: float | None = None
    count: int | None = None
    review: str = ""


class EventIn(BaseModel):
    """Нормализованное событие. Ключи — как в модели Event (п. 6.1)."""

    slug: str
    title: str = Field(min_length=3, max_length=300)
    category: str = Field(min_length=2, max_length=80)
    subcategory: str = Field(default="", max_length=80)
    kind: str = "событие"
    city: str = Field(default="Москва", max_length=80)
    dates: list[date] = Field(min_length=1)
    time_text: str = Field(default="", max_length=200)
    start_time: time | None = None
    end_time: time | None = None
    duration_min: int | None = Field(default=None, ge=0, le=24 * 60 * 14)
    venue: str = ""
    address: str = ""
    metro: str = Field(default="", max_length=200)
    lat: float | None = None
    lon: float | None = None
    price_from: int | None = Field(default=None, ge=0)
    price_text: str = ""
    description: str = ""
    why_fit_hint: str = ""
    note: str = ""
    tags: list[str] = Field(default_factory=list)
    aesthetics: int = Field(default=3, ge=1, le=5)
    novelty: int = Field(default=3, ge=1, le=5)
    crowd: str = "камерно"
    audience_30plus: bool = True
    audience_kids: bool = False
    url: str = ""
    sources: list[str] = Field(default_factory=list)
    rating: RatingIn | None = None
    confidence: str = "вероятно"
    status: str = "draft"
    organizer_id: str | None = None

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        v = v.strip().lower()
        if not _SLUG_RE.match(v):
            raise ValueError("slug: латиница, цифры и дефис, 3–120 символов")
        return v

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in KINDS:
            raise ValueError(f"kind должен быть одним из {KINDS}")
        return v

    @field_validator("crowd")
    @classmethod
    def _crowd(cls, v: str) -> str:
        if v not in CROWD:
            raise ValueError(f"crowd должен быть одним из {CROWD}")
        return v

    @field_validator("confidence")
    @classmethod
    def _conf(cls, v: str) -> str:
        if v not in CONFIDENCE:
            raise ValueError(f"confidence должен быть одним из {CONFIDENCE}")
        return v

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        if v not in EVENT_STATUSES:
            raise ValueError(f"status должен быть одним из {EVENT_STATUSES}")
        return v

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        seen: list[str] = []
        for t in v:
            t = t.strip().lower()
            if t not in KNOWN_TAGS:
                raise ValueError(f"неизвестный тег «{t}» — теги только из справочника catalog.KNOWN_TAGS")
            if t not in seen:
                seen.append(t)
        return seen

    @field_validator("dates")
    @classmethod
    def _dates(cls, v: list[date]) -> list[date]:
        return sorted(set(v))

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = (v or "").strip()
        if v and (not v.startswith(("http://", "https://")) or any(not ch.isprintable() or ch.isspace() for ch in v)):
            raise ValueError("url: только http(s)-ссылка без пробелов")
        return v[:2000]

    @field_validator("sources")
    @classmethod
    def _sources(cls, v: list[str]) -> list[str]:
        out = []
        for u in v:
            u = (u or "").strip()
            if u and u.startswith(("http://", "https://")) and all(ch.isprintable() and not ch.isspace() for ch in u):
                out.append(u[:2000])
        return out

    @model_validator(mode="after")
    def _derive_times(self) -> "EventIn":
        """start_time/end_time выводятся из time_text, если не заданы явно."""
        if self.start_time is None and self.time_text:
            s = hhmm(start_hour(self.time_text))
            self.start_time = time.fromisoformat(s) if s else None
        if self.end_time is None and self.time_text and self.start_time is not None:
            e = hhmm(end_hour({"time_text": self.time_text, "duration_min": self.duration_min}))
            self.end_time = time.fromisoformat(e) if e else None
        return self

    def as_core(self) -> dict[str, Any]:
        """Словарь для ядра (даты — ISO-строки, как в прототипе)."""
        d = self.model_dump()
        d["dates"] = [x.isoformat() for x in self.dates]
        d["start_time"] = self.start_time.isoformat(timespec="minutes") if self.start_time else None
        d["end_time"] = self.end_time.isoformat(timespec="minutes") if self.end_time else None
        d["id"] = self.slug
        return d


class RawEvent(BaseModel):
    """Сырая карточка из коллектора (п. 7.1): то, что видно в источнике до нормализации."""

    source: str
    url: str
    title: str
    date_text: str = ""
    text: str = ""
    venue: str = ""
    price_text: str = ""
    collected_at: str = ""
    # Структурные поля: необязательные, коллектор заполняет то, что источник отдаёт отдельно от текста.
    # Пустое значение означает «источник не сообщил», в промпт нормализатора такие поля не попадают.
    place_name: str = ""  # название места в справочнике источника, если оно отличается от `venue` (зал, сцена)
    address: str = ""
    metro: str = ""
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    age_restriction: str = ""  # как в источнике: «6+», «18+»
    categories: list[str] = Field(default_factory=list)  # категории источника как есть (slug или название)
