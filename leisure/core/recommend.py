"""Рекомендация на уикенд и состав дайджеста (п. 8 спеки). Перенос recommend() и kindBonus() прототипа.

Добавлено по спеке: исключение показанного в прошлых дайджестах без реакции, «на горизонте» (score ≥ 70,
до 2 событий с продажами), не больше одного продвигаемого события в дайджесте.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from .config import scoring_config
from .scoring import ScoreResult, score_events
from .timeutil import event_dates, is_horizon, reco_slot, weekend_days

NO_FILL = ("мимо", "интересно", "пропуск")  # никогда не заполняют слот


@dataclass
class SlotPick:
    day: str
    slot: str
    event: dict | None
    chosen: bool = False
    result: ScoreResult | None = None

    def as_item(self, why_limit: int | None = None) -> dict | None:
        if self.event is None:
            return None
        return {
            "event_id": str(self.event.get("id") or self.event.get("slug")),
            "slug": self.event.get("slug"),
            "day": self.day,
            "slot": self.slot,
            "chosen": self.chosen,
            "score": self.result.score if self.result else None,
            "why": self.result.why_dicts(why_limit) if self.result else [],
        }


@dataclass
class Digest:
    weekend: list[str]
    slots: list[SlotPick]
    horizon: list[tuple[dict, ScoreResult]] = field(default_factory=list)

    def items(self, why_limit: int | None = None) -> list[dict]:
        """Элементы дайджеста; why обрезается через trim_why (негативные причины не теряются)."""
        out = [p.as_item(why_limit) for p in self.slots if p.event is not None]
        for ev, r in self.horizon:
            out.append({
                "event_id": str(ev.get("id") or ev.get("slug")), "slug": ev.get("slug"),
                "day": event_dates(ev)[0] if event_dates(ev) else None, "slot": "горизонт", "chosen": False,
                "score": r.score, "why": r.why_dicts(why_limit),
            })
        return out

    def event_ids(self) -> list[str]:
        return [it["event_id"] for it in self.items()]


def kind_bonus(ev: Mapping, cfg: dict | None = None) -> float:
    kb = (cfg or scoring_config())["recommend"]["kind_bonus"]
    return float(kb.get(ev.get("kind") or "", 0))


def _id(ev: Mapping) -> str:
    return str(ev.get("id") or ev.get("slug"))


def recommend_slots(events: Sequence[Mapping], scores: Mapping[str, ScoreResult], profile: Mapping,
                    decisions_by_id: Mapping[str, Mapping], weekend: Sequence[str], cfg: dict | None = None,
                    exclude_ids: Iterable[str] = ()) -> list[SlotPick]:
    """5 слотов: пт вечер, сб день, сб вечер, вс день, вс вечер. Сначала «иду», затем лучший кандидат."""
    cfg = cfg or scoring_config()
    R = cfg["recommend"]
    interests: Mapping = profile.get("interests") or {}
    default_interest = cfg["interest"]["default_level"]
    exclude = set(map(str, exclude_ids))
    used: set[str] = set()
    promoted_used = 0
    out: list[SlotPick] = []

    for day_idx, slot in R["slots"]:
        if day_idx >= len(weekend):
            continue
        day = weekend[day_idx]
        chosen = None
        for ev in events:
            d = decisions_by_id.get(_id(ev))
            if not d or d.get("status") != "иду" or is_horizon(ev, weekend):
                continue
            wd = weekend_days(ev, weekend)
            if day in wd and (d.get("day") or wd[0]) == day and reco_slot(ev) == slot:
                chosen = ev
                break
        if chosen is not None:
            used.add(_id(chosen))
            out.append(SlotPick(day, slot, dict(chosen), True, scores.get(_id(chosen))))
            continue

        cands = []
        for ev in events:
            eid = _id(ev)
            if eid in used or eid in exclude or is_horizon(ev, weekend):
                continue
            if day not in weekend_days(ev, weekend) or reco_slot(ev) != slot:
                continue
            d = decisions_by_id.get(eid)
            if d and (d.get("status") in NO_FILL or d.get("status") == "иду"):
                continue  # «иду» закрепляется в своём слоте выше и не дублируется как кандидат
            if int(interests.get(ev.get("category") or "", default_interest) or 0) <= 0:
                continue
            r = scores.get(eid)
            if r is None:
                continue
            cands.append((r.score + kind_bonus(ev, cfg), ev, r))
        cands.sort(key=lambda c: -c[0])  # устойчиво: при равенстве — порядок событий
        pick = None
        for _, ev, r in cands:
            if r.promoted and promoted_used >= int(cfg["promotion"]["max_per_digest"]):
                continue
            pick = (ev, r)
            break
        if pick:
            ev, r = pick
            used.add(_id(ev))
            if r.promoted:
                promoted_used += 1
            out.append(SlotPick(day, slot, dict(ev), False, r))
        else:
            out.append(SlotPick(day, slot, None))
    return out


def horizon_picks(events: Sequence[Mapping], scores: Mapping[str, ScoreResult], decisions_by_id: Mapping[str, Mapping],
                  weekend: Sequence[str], cfg: dict | None = None, exclude_ids: Iterable[str] = ()) -> list[tuple[dict, ScoreResult]]:
    """До 2 событий дальше уикенда с продажами (есть ссылка) и score ≥ 70."""
    cfg = cfg or scoring_config()
    R = cfg["recommend"]
    exclude = set(map(str, exclude_ids))
    pool = []
    for ev in events:
        eid = _id(ev)
        if eid in exclude or not is_horizon(ev, weekend) or not ev.get("url"):
            continue
        d = decisions_by_id.get(eid)
        if d and d.get("status") in NO_FILL:
            continue
        r = scores.get(eid)
        if r is None or r.score < int(R["horizon_min_score"]):
            continue
        pool.append((ev, r))
    pool.sort(key=lambda er: (-er[1].score, event_dates(er[0])[0] if event_dates(er[0]) else "9999"))
    return [(dict(ev), r) for ev, r in pool[: int(R["horizon_max"])]]


def build_digest(events: Sequence[Mapping], profile: Mapping, decisions: Iterable[Mapping], weekend: Sequence[str],
                 cfg: dict | None = None, recently_shown: Iterable[str] = (), now: datetime | None = None,
                 scores: Mapping[str, ScoreResult] | None = None) -> Digest:
    """Полный состав дайджеста для одного пользователя.

    events — опубликованные события с будущими датами (см. timeutil.trim_past);
    decisions — решения пользователя; recently_shown — id событий из последних N дайджестов без реакции.
    """
    cfg = cfg or scoring_config()
    decisions = list(decisions)
    recent = set(map(str, recently_shown))
    by_id = {str(d.get("event_id") or d.get("id")): d for d in decisions}
    if scores is None:
        scores = score_events(events, profile, decisions, cfg, now=now)
    slots = recommend_slots(events, scores, profile, by_id, weekend, cfg, recent)
    taken = {_id(p.event) for p in slots if p.event}
    horizon = horizon_picks(events, scores, by_id, weekend, cfg, recent | taken)
    return Digest(list(weekend), slots, horizon)
