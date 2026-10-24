"""Типы колонок с вариантами: PostgreSQL — массивы/JSONB, SQLite (тесты) — JSON."""
from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.types import JSON, TypeDecorator

JSONType = JSON().with_variant(JSONB(), "postgresql")
TextList = ARRAY(Text()).with_variant(JSON(), "sqlite")


class DateList(TypeDecorator):
    """date[] в PostgreSQL; в остальных диалектах — JSON-список ISO-строк."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(ARRAY(Date()))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return [date.fromisoformat(str(v)[:10]) if not isinstance(v, date) else v for v in value]
        return [v.isoformat() if isinstance(v, date) else str(v)[:10] for v in value]

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return [v if isinstance(v, date) else date.fromisoformat(str(v)[:10]) for v in value]
