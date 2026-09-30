"""Общий матчинг условий из YAML: {вопрос: код} или {вопрос: [коды]}."""
from __future__ import annotations

from typing import Any, Mapping


def _as_set(v: Any) -> set[str]:
    return {str(x) for x in v} if isinstance(v, list) else {str(v)}


def match_all(cond: Mapping[str, Any] | None, answers: Mapping[str, str]) -> bool:
    """Все условия выполнены одновременно. Пустое условие — всегда True."""
    for q, v in (cond or {}).items():
        if answers.get(str(q)) not in _as_set(v):
            return False
    return True


def match_none(cond: Mapping[str, Any] | None, answers: Mapping[str, str]) -> bool:
    """Ни одно из условий не выполнено (для when_not)."""
    for q, v in (cond or {}).items():
        if answers.get(str(q)) in _as_set(v):
            return False
    return True
