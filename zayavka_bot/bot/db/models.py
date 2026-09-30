"""Модель данных (раздел 9 ТЗ). Время везде — naive UTC.

Отступление от ТЗ: в users добавлено поле stage — этап заявки хранится в БД,
а не в памяти FSM, поэтому рестарт не теряет, на каком вопросе человек.
Таблицы slots и bookings созданы сразу, используются в полной версии.
Миграция 0002: согласие галочкой, платная подписка, рассылки.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)  # tg_id
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    source: Mapped[str] = mapped_column(String(32), default="direct")
    ref: Mapped[str | None] = mapped_column(String(64))
    stage: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    nurture_enabled: Mapped[bool] = mapped_column(Boolean, default=True)  # «Сообщения от меня» в /menu
    consent_at: Mapped[datetime | None] = mapped_column(DateTime)  # галочка согласия на обработку ПД
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)


class Answer(Base):
    __tablename__ = "answers"
    __table_args__ = (UniqueConstraint("user_id", "q_code", name="uq_answers_user_q"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    q_code: Mapped[str] = mapped_column(String(32))
    a_code: Mapped[str] = mapped_column(String(32))
    answered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Lead(Base):
    __tablename__ = "leads"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), primary_key=True)
    phone: Mapped[str | None] = mapped_column(String(32))
    company: Mapped[str | None] = mapped_column(String(256))
    consent_at: Mapped[datetime | None] = mapped_column(DateTime)
    score: Mapped[int | None] = mapped_column(Integer)
    segment: Mapped[str | None] = mapped_column(String(32), index=True)
    session_type: Mapped[str | None] = mapped_column(String(32))
    session_type_2: Mapped[str | None] = mapped_column(String(32))
    verdict: Mapped[str | None] = mapped_column(String(32))
    report_path: Mapped[str | None] = mapped_column(String(512))
    report_json: Mapped[dict | None] = mapped_column(JSON)
    contacted_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Slot(Base):
    __tablename__ = "slots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime)
    duration_min: Mapped[int] = mapped_column(Integer, default=30)
    booked_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    slot_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("slots.id"))
    status: Mapped[str] = mapped_column(String(16), default="booked")  # booked|done|no_show|cancelled
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    kind: Mapped[str] = mapped_column(String(64))
    run_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending|done|cancelled|failed
    note: Mapped[str | None] = mapped_column(Text)


class Subscription(Base):
    """Платная подписка на бизнес-новости. Одна строка на человека, продление сдвигает paid_until."""
    __tablename__ = "subscriptions"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), primary_key=True)
    paid_until: Mapped[datetime] = mapped_column(DateTime, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    amount: Mapped[int] = mapped_column(Integer)  # в минимальных единицах: копейки или звёзды
    currency: Mapped[str] = mapped_column(String(8))
    days: Mapped[int] = mapped_column(Integer)
    telegram_charge_id: Mapped[str] = mapped_column(String(128), unique=True)
    provider_charge_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Broadcast(Base):
    """Рассылка: важный пост канала (digest) или новость для подписчиков (news)."""
    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))  # digest | news
    from_chat_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int] = mapped_column(Integer)
    post_url: Mapped[str | None] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|sending|sent|cancelled
    audience: Mapped[str | None] = mapped_column(String(16))
    sent: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
