"""Живая лента (docs/PIVOT-PWA.md, версия 2): события на день или период с рангом по профилю.

Чистая функция без БД и сети: события в формате ядра, профиль, решения, момент «сейчас». Ранжирование — тот же score(), что у
подборки; прежний recommend() не затронут (паритет с прототипом держится отдельно). Для сегодняшнего дня исключается всё, что
начинается раньше now + travel_minutes (время в пути из профиля), выставки и места — только после end_time.
"""
from __future__ import annotations

import copy
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .catalog import BUSINESS_CATS
from .config import scoring_config
from .scoring import ScoreResult, score_events
from .timeutil import _gone_today, event_dates

SEGMENTS = ("leisure", "business", "all")
WEEK_DAYS = 7
HIDDEN_STATUSES = ("мимо", "не моё", "пропуск", "не сходил", "сходил")   # уже отвечено «нет» или сделано: в ленте не показываем


@dataclass
class FeedItem:
    event: dict
    day: str                      # первый день окна, на который успеваешь
    days: list[str]               # все подходящие дни окна
    result: ScoreResult
    can_make_it: bool


@dataclass
class FeedPage:
    items: list[FeedItem]
    offset: int
    total: int                    # сколько всего карточек в ленте (после всех фильтров и лимита на день)

    @property
    def next_offset(self) -> int | None:
        nxt = self.offset + len(self.items)
        return nxt if nxt < self.total else None


def parse_window(spec: str, today: date) -> list[date]:
    """today | tomorrow | week (сегодня + 6 дней) | YYYY-MM-DD → список дней окна. Прошедшая дата и мусор — ValueError."""
    s = (spec or "today").strip().lower()
    if s == "today":
        return [today]
    if s == "tomorrow":
        return [today + timedelta(days=1)]
    if s == "week":
        return [today + timedelta(days=i) for i in range(WEEK_DAYS)]
    try:
        d = date.fromisoformat(s)
    except ValueError as e:
        raise ValueError("date: today, tomorrow, week или YYYY-MM-DD") from e
    if d < today:
        raise ValueError("date: день уже прошёл")
    return [d]


def in_segment(ev: Mapping, segment: str) -> bool:
    """business = четыре бизнес-категории каталога, leisure = остальные, all = всё."""
    if segment == "all":
        return True
    is_business = (ev.get("category") or "") in BUSINESS_CATS
    return is_business if segment == "business" else not is_business


def hidden_by_learning(ev: Mapping, aff: Mapping | None, cfg: dict | None = None) -> bool:
    """«Не показывать похожее»: категория события или все его теги (не меньше двух) на пороге отрицательного affinity или ниже."""
    if not aff or not aff.get("n"):
        return False
    L = (cfg or scoring_config())["learning"]
    cat = float((aff.get("cat") or {}).get(ev.get("category") or "", 0.0))
    if cat <= float(L["hide_category_below"]):
        return True
    tags = [t for t in (ev.get("tags") or []) if t in (aff.get("tag") or {})]
    if len(ev.get("tags") or []) >= 2 and len(tags) == len(ev.get("tags") or []):
        return all(float(aff["tag"][t]) <= float(L["hide_tag_below"]) for t in tags)
    return False


def adult_only(ev: Mapping, cfg: dict | None = None) -> bool:
    """Не для профиля-ребёнка: категория, тег или слово в названии из audience_child (scoring.yaml)."""
    A = (cfg or scoring_config()).get("audience_child") or {}
    if (ev.get("category") or "") in (A.get("exclude_categories") or ()):
        return True
    if set(ev.get("tags") or []) & set(A.get("exclude_tags") or ()):
        return True
    text = " ".join(str(ev.get(k) or "") for k in ("title", "subcategory")).lower()
    return any(re.search(p, text) for p in (A.get("exclude_patterns") or ()))


def can_make_it(ev: Mapping, day: date, today: date, now: datetime | None, travel_minutes: int) -> bool:
    """Успеваешь ли: на сегодня — старт не раньше now + travel_minutes (выставки и места — пока не закрылись); на другие дни — да."""
    if now is None or day != today or now.date() != today:
        return True
    return not _gone_today(ev, now.hour * 60 + now.minute, travel_minutes)


def feed_profile(profile: Mapping, cfg: dict) -> tuple[dict, dict | None, dict]:
    """Профиль, affinity и конфиг для ранжирования ленты: служебные теги не несут сигнала, потолок обучения из feed.learning,
    у ребёнка включён режим «с детьми» (+детское, −ночное и шумное)."""
    F = cfg["feed"]
    prof = dict(profile)
    if profile.get("kind") == "child":
        prof["params"] = {**(profile.get("params") or {}), "kids": True}
    aff = profile.get("affinity") or None
    if aff and aff.get("n"):
        ignore = set(F.get("ignore_tags") or ())
        aff = {**aff, "tag": {t: w for t, w in (aff.get("tag") or {}).items() if t not in ignore}}
    fcfg = cfg
    if F.get("learning"):
        fcfg = copy.deepcopy(cfg)
        fcfg["learning"].update(F["learning"])
    return prof, aff, fcfg


def build_feed(events: Iterable[Mapping], profile: Mapping, decisions: Sequence[Mapping], days: Sequence[date], today: date,
               now: datetime | None = None, segment: str = "all", travel_minutes: int | None = None, limit: int | None = None,
               include_missed: bool = False, cfg: dict | None = None, per_day: int | None = None, offset: int = 0) -> FeedPage:
    """Ранжированная лента на окно days. now — местное время профиля (без него время суток не учитывается).

    Событие попадает один раз: day — первый подходящий день окна. Скрыты: чужой сегмент, события, на которые уже ответили
    «нет» или которые сделаны, «похожее» на отклонённое (hidden_by_learning) и взрослое у профиля-ребёнка. include_missed=True
    добавляет события, на которые на сегодня уже не успеть (can_make_it = False) — после успевающих. На период (дней больше одного)
    на каждый день не больше per_day карточек (feed.per_day); offset/limit — страница, total и next_offset — для догрузки."""
    cfg = cfg or scoring_config()
    F = cfg["feed"]
    if travel_minutes is None:
        travel_minutes = (profile.get("params") or {}).get("travel_minutes")
    travel = int(travel_minutes if travel_minutes is not None else F["travel_minutes"])
    limit = max(1, min(int(limit or F["default_limit"]), int(F["max_limit"])))
    offset = max(0, int(offset or 0))
    cap = int(per_day if per_day is not None else F.get("per_day") or 0)
    prof, aff, fcfg = feed_profile(profile, cfg)
    child = profile.get("kind") == "child"
    done = {str(d.get("event_id")) for d in decisions if d.get("status") in HIDDEN_STATUSES}
    window = {d.isoformat(): d for d in days}
    cands: list[tuple[dict, list[str], list[str]]] = []
    for ev in events:
        if str(ev.get("id")) in done or not in_segment(ev, segment) or hidden_by_learning(ev, aff, cfg):
            continue
        if child and adult_only(ev, cfg):
            continue
        ds = [d for d in sorted(event_dates(ev)) if d in window]
        if not ds:
            continue
        ok = [d for d in ds if can_make_it(ev, window[d], today, now, travel)]
        if not ok and not include_missed:
            continue
        cands.append((dict(ev), ok, ds))
    decs = list(decisions)
    scores = score_events([c[0] for c in cands], prof, decs, aff=aff, cfg=fcfg)
    items = []
    for ev, ok, ds in cands:
        items.append(FeedItem(ev, (ok or ds)[0], ok or ds, scores[str(ev.get("id") or ev.get("slug"))], bool(ok)))
    items.sort(key=lambda it: (not it.can_make_it, -it.result.score, it.day, it.event.get("title") or ""))
    if len(days) > 1 and cap > 0:
        per: dict[str, int] = {}
        kept = []
        for it in items:
            if per.get(it.day, 0) < cap:
                per[it.day] = per.get(it.day, 0) + 1
                kept.append(it)
        items = kept
    return FeedPage(items[offset:offset + limit], offset, len(items))
