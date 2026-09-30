"""Ответы → тип сессии (раздел 5 ТЗ). Правила — content/mapping.yaml."""
from __future__ import annotations

from typing import Any, Mapping

from bot.services.rules import match_all


def session_types(answers: Mapping[str, str], mapping: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """(основной, дополнительный). Дополнительный — следующий сработавший тип, отличный от основного."""
    found: list[str] = []
    for rule in mapping["rules"]:
        t = str(rule["type"])
        if t in found:
            continue
        if any(match_all(cond, answers) for cond in rule.get("any") or []):
            found.append(t)
            if len(found) == 2:
                break
    return (found[0] if found else None, found[1] if len(found) > 1 else None)


def type_label(code: str | None, mapping: Mapping[str, Any]) -> str:
    if not code:
        return "—"
    return str(mapping.get("labels", {}).get(code, code))
