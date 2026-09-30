"""Два наблюдения по ответам до запроса телефона (п. 3.4). Без LLM, по content/insights.yaml."""
from __future__ import annotations

from typing import Any, Mapping

from bot.services.rules import match_all


def pick(answers: Mapping[str, str], insights: Mapping[str, Any]) -> tuple[str, str]:
    """Первое подходящее из first, первое подходящее из second, иначе default."""
    out = []
    for block in ("first", "second"):
        text = None
        for rule in insights.get(block) or []:
            if match_all(rule.get("when"), answers):
                text = str(rule["text"]).strip()
                break
        out.append(text or str(insights["default"][block]).strip())
    return out[0], out[1]
