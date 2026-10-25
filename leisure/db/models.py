"""Модели БД (п. 6 спеки): Event, Profile, Decision, Digest, Organizer. SQLAlchemy 2.0, PostgreSQL 16.

Отличия от текста спеки — только добавления: Event.note и Event.rating (были в прототипе и нужны куратору),
Event.lat/lon вместо point (без PostGIS), Decision.event_slug в снимке, Profile.name/username/consent_at (152-ФЗ).
Эмбеддинги (pgvector) — второй этап, колонка добавится отдельной миграцией.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time

from sqlalchemy import (BigInteger, Boolean, Date, DateTime, Enum, Float, ForeignKey, Index, Integer, SmallInteger,
                        String, Text, Time, UniqueConstraint, func)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from leisure.core.catalog import (CONFIDENCE, CROWD, DECISION_STATUSES, EVENT_STATUSES, INVITE_KINDS, INVITE_STATUSES, KINDS, PLANS,
                                  PROFILE_KINDS, PROFILE_SOURCES)

from .types import DateList, JSONType, TextList


def _enum(values: list[str], name: str) -> Enum:
    # VARCHAR + CHECK вместо нативного enum: справочники меняются без ALTER TYPE.
    return Enum(*values, name=name, native_enum=False, create_constraint=True, validate_strings=True, length=24)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Organizer(Base, TimestampMixin):
    __tablename__ = "organizers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    contact: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    events: Mapped[list["Event"]] = relationship(back_populates="organizer")

    def __str__(self) -> str:
        return self.name


class Event(Base, TimestampMixin):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_status_city", "status", "city"),
        Index("ix_events_dates_gin", "dates", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    subcategory: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    kind: Mapped[str] = mapped_column(_enum(KINDS, "event_kind"), default="событие", nullable=False)
    city: Mapped[str] = mapped_column(String(80), default="Москва", nullable=False)
    dates: Mapped[list[date]] = mapped_column(DateList, nullable=False)
    time_text: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    duration_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    venue: Mapped[str] = mapped_column(Text, default="", nullable=False)
    address: Mapped[str] = mapped_column(Text, default="", nullable=False)
    metro: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_from: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0 = бесплатно
    price_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    why_fit_hint: Mapped[str] = mapped_column(Text, default="", nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    tags: Mapped[list[str]] = mapped_column(TextList, default=list, nullable=False)
    aesthetics: Mapped[int] = mapped_column(SmallInteger, default=3, nullable=False)
    novelty: Mapped[int] = mapped_column(SmallInteger, default=3, nullable=False)
    crowd: Mapped[str] = mapped_column(_enum(CROWD, "event_crowd"), default="камерно", nullable=False)
    audience_30plus: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    audience_kids: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sources: Mapped[list[str]] = mapped_column(TextList, default=list, nullable=False)
    rating: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    confidence: Mapped[str] = mapped_column(_enum(CONFIDENCE, "event_confidence"), default="вероятно", nullable=False)
    status: Mapped[str] = mapped_column(_enum(EVENT_STATUSES, "event_status"), default="draft", index=True, nullable=False)
    organizer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizers.id", ondelete="SET NULL"), nullable=True)
    promoted_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organizer: Mapped[Organizer | None] = relationship(back_populates="events")

    CORE_FIELDS = (
        "slug", "title", "category", "subcategory", "kind", "city", "time_text", "duration_min", "venue", "address",
        "metro", "lat", "lon", "price_from", "price_text", "description", "why_fit_hint", "note", "tags", "aesthetics",
        "novelty", "crowd", "audience_30plus", "audience_kids", "url", "sources", "rating", "confidence", "status",
    )

    def as_core(self) -> dict:
        """Словарь для ядра: id — строковый uuid, даты — ISO."""
        d = {k: getattr(self, k) for k in self.CORE_FIELDS}
        d["id"] = str(self.id)
        d["dates"] = [x.isoformat() for x in (self.dates or [])]
        d["start_time"] = self.start_time.isoformat(timespec="minutes") if self.start_time else None
        d["end_time"] = self.end_time.isoformat(timespec="minutes") if self.end_time else None
        d["promoted_until"] = self.promoted_until.isoformat() if self.promoted_until else None
        d["organizer_id"] = str(self.organizer_id) if self.organizer_id else None
        return d

    def __str__(self) -> str:
        return self.title


class Account(Base):
    """Аккаунт веб-сессии: гость с первого экрана, почта по желанию (magic link). Данные людей лежат в profiles."""
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)    # из guest_user_id_seq
    email: Mapped[str | None] = mapped_column(String(254), unique=True, nullable=True)    # в нижнем регистре; null — не привязана
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    profiles: Mapped[list["Profile"]] = relationship(back_populates="account", order_by="Profile.created_at", passive_deletes=True)


class Profile(Base, TimestampMixin):
    __tablename__ = "profiles"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)  # id гостевой сессии (POST /api/session); у старых профилей — бывший Telegram id
    name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    username: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    city: Mapped[str] = mapped_column(String(80), default="Москва", nullable=False)
    values: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)       # {ценность: 0–5}
    interests: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)    # {категория: 0–3}
    params: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)       # aesthetics, adults30, kids, budget, company, times[], areas[]
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    tz: Mapped[str] = mapped_column(String(64), default="Europe/Moscow", nullable=False)
    digest_day: Mapped[int] = mapped_column(SmallInteger, default=4, nullable=False)   # ISO-день недели: 4 = четверг
    digest_hour: Mapped[int] = mapped_column(SmallInteger, default=19, nullable=False)
    plan: Mapped[str] = mapped_column(_enum(PLANS, "profile_plan"), default="free", nullable=False)
    affinity: Mapped[dict] = mapped_column(JSONType, default=lambda: {"tag": {}, "cat": {}, "n": 0}, nullable=False)
    affinity_manual: Mapped[dict] = mapped_column(JSONType, default=lambda: {"tag": {}, "cat": {}}, nullable=False)  # ручная правка: прибавка к вычисленному
    affinity_manual_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    onboarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # рост через друзей (docs/GROWTH.md): откуда пришёл, кто позвал, показывать ли имя друзьям
    source: Mapped[str] = mapped_column(_enum(PROFILE_SOURCES, "profile_source"), default="organic", server_default="organic", nullable=False)
    referred_by: Mapped[int | None] = mapped_column(ForeignKey("profiles.user_id", ondelete="SET NULL"), nullable=True)
    show_name: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    # Человек разрешил приложению присылать push (веб ставит PUT can_write после диалога разрешения). «Входящие» работают и при false.
    can_write: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    # Несколько профилей на аккаунт (docs/PIVOT-PWA.md, версия 2): «я», «мама», «ребёнок». user_id — идентификатор профиля;
    # у профиля «я», созданного гостевой сессией, он совпадает с id аккаунта.
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(_enum(PROFILE_KINDS, "profile_kind"), default="self", server_default="self", nullable=False)
    offer_seen: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0", nullable=False)   # предложение своей подборки приглашённому: 0 не показывали, 1 показали («Потом»), 2 повтор показан или «Не нужно»

    # Когда повторить предложение онбординга приглашённому: день события по приглашению + 1 (ставит принятие going/maybe, один раз)
    offer_due: Mapped[date | None] = mapped_column(Date, nullable=True)

    account: Mapped[Account] = relationship(back_populates="profiles")
    decisions: Mapped[list["Decision"]] = relationship(back_populates="profile", cascade="all, delete-orphan")
    digests: Mapped[list["Digest"]] = relationship(back_populates="profile", cascade="all, delete-orphan")

    def as_core(self) -> dict:
        return {
            "user_id": self.user_id, "kind": self.kind, "city": self.city, "values": dict(self.values or {}),
            "interests": dict(self.interests or {}), "params": dict(self.params or {}), "notes": self.notes,
            "tz": self.tz, "plan": self.plan, "affinity": dict(self.affinity or {}),
        }

    def __str__(self) -> str:
        return f"{self.name or self.username or self.user_id}"


class Decision(Base, TimestampMixin):
    __tablename__ = "decisions"
    __table_args__ = (
        UniqueConstraint("user_id", "event_id", name="uq_decisions_user_event"),
        Index("ix_decisions_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("profiles.user_id", ondelete="CASCADE"), index=True, nullable=False)
    event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("events.id", ondelete="SET NULL"), index=True, nullable=True)
    status: Mapped[str] = mapped_column(_enum(DECISION_STATUSES, "decision_status"), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    day: Mapped[date | None] = mapped_column(Date, nullable=True)
    rating: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    invite_id: Mapped[int | None] = mapped_column(ForeignKey("invites.id", ondelete="SET NULL"), nullable=True)   # решение пришло через приглашение
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)        # «План на сегодня» отправлен
    feedback_asked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # «Как прошло?» отправлено
    # снимок события — обучение переживает удаление события
    event_slug: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    event_category: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    event_tags: Mapped[list[str]] = mapped_column(TextList, default=list, nullable=False)

    profile: Mapped[Profile] = relationship(back_populates="decisions")
    event: Mapped[Event | None] = relationship()

    def as_core(self) -> dict:
        return {
            "event_id": str(self.event_id) if self.event_id else self.event_slug, "status": self.status,
            "reason": self.reason or "", "day": self.day.isoformat() if self.day else "", "rating": self.rating or 0,
            "event_category": self.event_category, "event_tags": list(self.event_tags or []),
        }


class Digest(Base):
    __tablename__ = "digests"
    __table_args__ = (UniqueConstraint("user_id", "weekend_start", name="uq_digests_user_weekend"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("profiles.user_id", ondelete="CASCADE"), index=True, nullable=False)
    weekend_start: Mapped[date] = mapped_column(Date, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    items: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)  # [{event_id, slug, score, why[], slot, day}]
    opened: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    decisions_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    plan_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)      # «План на сегодня»
    feedback_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # «Как прошло?»
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    profile: Mapped[Profile] = relationship(back_populates="digests")


class Invite(Base):
    """Приглашение (docs/GROWTH.md): kind='event' — «Позвать друга на мероприятие», kind='ref' — рекомендация сервиса."""
    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(8), unique=True, index=True, nullable=False)
    inviter_id: Mapped[int | None] = mapped_column(ForeignKey("profiles.user_id", ondelete="SET NULL"), index=True, nullable=True)   # NULL: пригласивший удалил профиль
    event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("events.id", ondelete="SET NULL"), nullable=True)
    event_slug: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    day: Mapped[date | None] = mapped_column(Date, nullable=True)
    kind: Mapped[str] = mapped_column(_enum(INVITE_KINDS, "invite_kind"), default="event", nullable=False)
    opened: Mapped[int] = mapped_column(Integer, default=0, nullable=False)       # сколько разных людей открыло
    accepted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)     # сколько приняло («иду» / «может быть»; для ref — начали онбординг)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    inviter: Mapped[Profile | None] = relationship(foreign_keys=[inviter_id])
    event: Mapped[Event | None] = relationship()
    accepts: Mapped[list["InviteAccept"]] = relationship(back_populates="invite", cascade="all, delete-orphan")


class InviteAccept(Base):
    __tablename__ = "invite_accepts"
    __table_args__ = (UniqueConstraint("invite_id", "user_id", name="uq_invite_accepts_invite_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invite_id: Mapped[int] = mapped_column(ForeignKey("invites.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("profiles.user_id", ondelete="CASCADE"), index=True, nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(_enum(INVITE_STATUSES, "invite_status"), default="opened", nullable=False)
    was_new: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)      # на момент открытия профиля или согласия не было
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)   # пригласивший уведомлён, что друг идёт

    invite: Mapped[Invite] = relationship(back_populates="accepts")


class GrowthEvent(Base):
    """Журнал событий роста, которые нельзя восстановить из других таблиц: показ момента рекомендации, нажатие «Поделиться»."""
    __tablename__ = "growth_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # null — открытие приглашения человеком без профиля или согласия (профиль не создаём, считаем только по коду)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("profiles.user_id", ondelete="CASCADE"), index=True, nullable=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)    # ref_ask | ref_share | invite_share | invite_open
    invite_code: Mapped[str | None] = mapped_column(String(8), index=True, nullable=True)
    # Псевдоним человека без согласия для одной ссылки (HMAC от кода и user_id с серверным ключом, 16 знаков): чтобы повторные
    # открытия не множили знаменатели метрик. Удаляется вместе со строкой, когда человек даёт согласие (появляется invite_accepts).
    visitor: Mapped[str | None] = mapped_column(String(16), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EmailToken(Base):
    """Одноразовая ссылка-вход по почте (15 минут). Токен хранится хешем; почта привязывается к аккаунту при подтверждении."""
    __tablename__ = "email_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
