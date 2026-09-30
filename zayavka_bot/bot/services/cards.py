"""Карточка лида для админа, строка для CRM, маскирование телефона."""
from __future__ import annotations

import re
from typing import Any, Mapping

from bot.content import Content
from bot.services.mapping import type_label

PHONE_RE = re.compile(r"\+?\d[\d\s()\-]{8,}\d")


def mask_phone(phone: str | None) -> str:
    """+79161234567 → +7***4567 (для логов, п. 13)."""
    if not phone:
        return "—"
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 5:
        return "***"
    return f"+{digits[0]}***{digits[-4:]}"


def mask_phones_in(text: str) -> str:
    return PHONE_RE.sub(lambda m: mask_phone(m.group(0)), text)


def normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    return "+" + digits if digits else phone


def tg_link(user_id: int, username: str | None) -> str:
    return f"https://t.me/{username}" if username else f"tg://user?id={user_id}"


def pain_text(c: Content, answers: Mapping[str, str]) -> str:
    """Боль словами клиента для {pain_text}: вариант ответа с маленькой буквы."""
    label = c.label("pain", answers.get("pain")) or ""
    return label[:1].lower() + label[1:] if label else label


def _lbl(c: Content, answers: Mapping[str, str], q: str, empty: str = "—") -> str:
    return c.label(q, answers.get(q)) or empty


def admin_card(
    c: Content,
    *,
    user_id: int,
    name: str | None,
    username: str | None,
    source: str | None,
    answers: Mapping[str, str],
    segment: str,
    score: int,
    session_type: str | None,
    session_type_2: str | None,
    phone: str | None,
    company: str | None,
) -> str:
    """Карточка по шаблону admin_card из texts.yaml. Отправляется без parse_mode."""
    if segment == "specialist":
        need = _lbl(c, answers, "specialist_need", "")
        role = _lbl(c, answers, "role")
        extra = f", нужно: {need}" if need else ""
        return (
            f"{c.texts['segment_icons']['specialist']} {c.texts['segment_labels']['specialist']}"
            f" | источник: {source or 'direct'} | {name or '—'} ({role}{extra})"
            f" | {tg_link(user_id, username)} | id {user_id}"
        )

    revenue = answers.get("revenue")
    card = c.t(
        "admin_card",
        segment_icon=c.texts["segment_icons"].get(segment, ""),
        segment_label=c.texts["segment_labels"].get(segment, segment),
        score=score,
        source=source or "direct",
        name=name or "—",
        company=company or "компания не указана",
        role=_lbl(c, answers, "role"),
        team_size=_lbl(c, answers, "team_size"),
        revenue="не указана" if revenue in (None, "skip") else _lbl(c, answers, "revenue"),
        timeline=_lbl(c, answers, "timeline"),
        pain=_lbl(c, answers, "pain"),
        outcome_6m=_lbl(c, answers, "outcome_6m"),
        strategy_state=_lbl(c, answers, "strategy_state"),
        decisions=_lbl(c, answers, "decisions"),
        tried=_lbl(c, answers, "tried"),
        participants=_lbl(c, answers, "participants"),
        session_type=type_label(session_type, c.mapping),
        session_type_2=type_label(session_type_2, c.mapping),
        phone=phone or "не оставил",
        tg_link=tg_link(user_id, username),
    )
    # В шаблоне нет отрасли, а промт разбора её ждёт; id нужен для /send.
    card += f"\nСфера: {_lbl(c, answers, 'industry')}\nID: {user_id}  (/send {user_id})"
    return card


SHEET_COLUMNS = [
    "created_at", "user_id", "name", "username", "phone", "company", "source", "role", "pain",
    "outcome_6m", "strategy_state", "decisions", "tried", "participants", "industry",
    "team_size", "revenue", "timeline", "score", "segment", "session_type", "verdict",
    "booking_at", "contacted_at", "status",
]
ANSWER_COLUMNS = SHEET_COLUMNS[7:18]


def sheet_row(c: Content, data: Mapping[str, Any]) -> list[str]:
    """Строка для листа leads. Ответы — текстом (читает человек), не кодами."""
    answers: Mapping[str, str] = data.get("answers") or {}
    row = []
    for col in SHEET_COLUMNS:
        if col in ANSWER_COLUMNS:
            a = answers.get(col)
            val = "" if a == "skip" else (c.label(col, a) or "")
        else:
            val = data.get(col)
        row.append("" if val is None else str(val))
    return row
