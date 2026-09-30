"""Разбор deep link /start <payload> (п. 3.1).

ig | tg | lecture | site           → source, ref = None
ig_reels1, lecture-spb             → source = ig / lecture, ref = хвост (utm-подобная метка)
ref_<код>                          → source = ref, ref = код
пусто                              → direct
что-то незнакомое                  → source = other, ref = payload целиком
"""
from __future__ import annotations

import re

KNOWN = ("ig", "tg", "lecture", "site")
_SAFE = re.compile(r"[^A-Za-z0-9_\-]")


def parse(payload: str | None) -> tuple[str, str | None]:
    p = _SAFE.sub("", (payload or "").strip())[:64]
    if not p:
        return "direct", None
    if p.startswith("ref_") and len(p) > 4:
        return "ref", p[4:]
    head, tail = _split(p)
    if head.lower() in KNOWN:
        return head.lower(), tail or None
    return "other", p


def _split(p: str) -> tuple[str, str]:
    m = re.match(r"^([^_\-]*)[_\-]?(.*)$", p)
    assert m
    return m.group(1), m.group(2)
