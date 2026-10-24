"""Обучение на решениях (п. 6.5 спеки): affinity() и learningBonus() прототипа с теми же числами.

Решение (Decision) несёт снимок категории и тегов события, поэтому обучение переживает удаление события.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping

from .config import scoring_config
from .timeutil import clamp


def _snapshot(d: Mapping, events_by_id: Mapping[str, Mapping] | None) -> tuple[str, list[str]] | None:
    """Категория и теги для решения: живое событие (если есть) → снимок в решении."""
    ev = None
    if events_by_id is not None:
        key = d.get("event_id") or d.get("id") or d.get("slug")
        ev = events_by_id.get(str(key)) if key is not None else None
    if ev is not None:
        return str(ev.get("category") or ""), list(ev.get("tags") or [])
    cat = d.get("event_category") or d.get("category") or ""
    tags = list(d.get("event_tags") or d.get("tags") or [])
    if not cat and not tags:
        return None
    return str(cat), tags


def decision_weight(d: Mapping, cfg: dict | None = None) -> float | None:
    """Вес сигнала решения; None — сигнала нет («пропуск»/«Другое»)."""
    L = (cfg or scoring_config())["learning"]
    status = d.get("status")
    if status not in L["decision_weights"]:
        return None
    w = L["decision_weights"][status]
    if w is None:
        return None
    w = float(w)
    if status == "мимо":
        rw = L["reason_weights"].get(d.get("reason") or "")
        if rw is not None:
            w = float(rw)
    rating = d.get("rating")
    if rating:
        w += (float(rating) - 3) / 2 * float(L["rating_scale"])
    return w


def compute_affinity(decisions: Iterable[Mapping], cfg: dict | None = None,
                     events_by_id: Mapping[str, Mapping] | None = None) -> dict:
    """{'tag': {тег: вес}, 'cat': {категория: вес}, 'n': число решений с сигналом}."""
    cfg = cfg or scoring_config()
    tag: dict[str, float] = {}
    cat: dict[str, float] = {}
    n = 0
    for d in decisions:
        snap = _snapshot(d, events_by_id)
        if snap is None:
            continue
        w = decision_weight(d, cfg)
        if w is None:
            continue
        n += 1
        c, tags = snap
        for t in tags:
            tag[t] = tag.get(t, 0.0) + w
        if c:
            cat[c] = cat.get(c, 0.0) + w
    return {"tag": tag, "cat": cat, "n": n}


EMPTY_AFFINITY: dict = {"tag": {}, "cat": {}, "n": 0}


def learning_bonus(ev: Mapping, aff: Mapping | None, cfg: dict | None = None) -> float:
    """clamp(avg(affinity.tag по тегам) × 3 + affinity.cat[category] × 2.5, −12, +12); 0 без решений."""
    if not aff or not aff.get("n"):
        return 0.0
    L = (cfg or scoring_config())["learning"]
    tags = aff.get("tag") or {}
    s = c = 0.0
    for t in ev.get("tags") or []:
        if t in tags:
            s += tags[t]
            c += 1
    tag_part = (s / c) * float(L["tag_multiplier"]) if c else 0.0
    cat_part = float((aff.get("cat") or {}).get(ev.get("category") or "", 0.0)) * float(L["category_multiplier"])
    lim = float(L["clamp"])
    return clamp(tag_part + cat_part, -lim, lim)


def describe_affinity(aff: Mapping, decisions: Iterable[Mapping] = (), top: int = 3) -> dict:
    """«Что я узнал о тебе» (п. 3.5): чаще выбираешь / чаще отклоняешь / причины «мимо»."""
    tag = aff.get("tag") or {}
    cat = aff.get("cat") or {}
    pool = [(k, v) for k, v in {**tag, **{c: v for c, v in cat.items()}}.items()]
    likes = [k for k, v in sorted(pool, key=lambda kv: -kv[1]) if v > 0][:top]
    dislikes = [k for k, v in sorted(pool, key=lambda kv: kv[1]) if v < 0][:top]
    reasons = Counter(d.get("reason") for d in decisions if d.get("status") == "мимо" and d.get("reason"))
    return {"likes": likes, "dislikes": dislikes, "reasons": dict(reasons.most_common()), "n": aff.get("n", 0)}


def describe_affinity_text(aff: Mapping, decisions: Iterable[Mapping] = ()) -> str:
    d = describe_affinity(aff, list(decisions))
    parts = []
    if d["likes"]:
        parts.append("чаще выбираешь: " + ", ".join(d["likes"]).lower())
    if d["dislikes"]:
        parts.append("чаще отклоняешь: " + ", ".join(d["dislikes"]).lower())
    if d["reasons"]:
        parts.append("причины «мимо»: " + ", ".join(f"{k} ({v})" for k, v in d["reasons"].items()))
    return "; ".join(parts) if parts else "пока мало решений — отметь несколько событий"
