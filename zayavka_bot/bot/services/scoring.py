"""Скоринг и сегментация (раздел 4 ТЗ). Правила — content/scoring.yaml.

role = other сегментируется как hr_dev (п. 3.3): это задано в самих правилах scoring.yaml.
"""
from __future__ import annotations

from typing import Any, Mapping

from bot.services.rules import match_all, match_none


def score(answers: Mapping[str, str], scoring: Mapping[str, Any]) -> int:
    total = 0
    for q, table in scoring["points"].items():
        a = answers.get(q)
        if a is not None:
            total += int(table.get(a, 0))
    return total


def segment(answers: Mapping[str, str], scoring: Mapping[str, Any]) -> tuple[str, int]:
    """Вернуть (сегмент, баллы). Правила проверяются сверху вниз."""
    s = score(answers, scoring)
    for rule in scoring["segments"]:
        min_score = rule.get("min_score")
        if min_score == "hot_threshold":
            min_score = scoring["hot_threshold"]
        if min_score is not None and s < int(min_score):
            continue
        if match_all(rule.get("when"), answers) and match_none(rule.get("when_not"), answers):
            return str(rule["segment"]), s
    return "specialist", s
