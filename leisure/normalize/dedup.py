"""Дедупликация событий без базы (п. 7, шаг 3 спеки): заголовок ~ площадка ~ пересечение дат.

Чистая логика: на входе EventIn, словари (seed, `as_core()`) или любые объекты с теми же атрибутами; БД не нужна.
Триграммная похожесть считается так же, как `similarity()` из pg_trgm (Жаккар по множествам триграмм слов с
пробельной подкладкой), так что пороги можно позже перенести в SQL без пересчёта. Эмбеддинги (вторая половина
пункта спеки) сюда не входят: это отдельный этап, он поймает «Metallica» против «Металлика».

Правило совпадения (все условия сразу):
  1. города совпадают (если заданы у обоих);
  2. у событий есть общий день показа (иначе это разные показы одного спектакля, а не дубликат);
  3. заголовки похожи (после нормализации), площадки похожи — либо одна из площадок не указана, но заголовки
     почти идентичны;
  4. у обычных событий начало не расходится на 3 часа и больше (дневной и вечерний показ — разные карточки).

Ложное склеивание хуже пропущенного дубля: склеенное событие пропадает из афиши молча, а пропущенный дубль куратор
увидит и уберёт одним кликом. Поэтому все пороги выбраны консервативно.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any

from leisure.core.catalog import CONFIDENCE

# ─── Пороги. Менять только вместе с тестами: каждый подтверждён парой «дубликат / не дубликат». ───

# Ниже этой похожести заголовков событие не считается дубликатом вообще. pg_trgm по умолчанию берёт 0.3, но для
# коротких русских заголовков общие окончания («-ого», «-ский») дают 0.3–0.4 у несвязанных названий; у «Гамлет» и
# «Гамлет-машина» (разные спектакли) выходит 0.5.
TITLE_MIN = 0.55
# Ниже этой похожести площадки считаются разными. Общее слово-тип даёт много общих триграмм: «Театр Маяковского»
# против «Музей Маяковского» — 0.52, «Музей А» против «Музей Б» — 0.60; это разные места, поэтому планка 0.7.
# Законные варианты записи («ГЭС-2» и «Дом культуры ГЭС-2», «Гараж» и «Музей «Гараж»») ловит правило вложенности
# слов в _venue_sim и без неё.
VENUE_MIN = 0.7
# Итог = 0.7·заголовок + 0.3·площадка: заголовок главный, площадка и даты подтверждают. При полностью совпавших
# площадке и датах порог 0.8 означает похожесть заголовков ≈ 0.72 и выше; при похожих, но не одинаковых площадках
# требования к заголовку выше.
TITLE_WEIGHT, VENUE_WEIGHT = 0.7, 0.3
DUP_THRESHOLD = 0.8
# Площадка не указана хотя бы у одного: итог = заголовок × 0.85, то есть дубликат только при заголовках, совпавших
# после нормализации (≥ 0.94); вложенный заголовок (0.9) без подтверждения площадкой уже не засчитываем.
UNKNOWN_VENUE_FACTOR = 0.85
# Один заголовок «вложен» в другой («Дюймовочка» и «Дюймовочка. Московский театр юного зрителя»): если почти все
# триграммы короткого (≥ 95 %) есть в длинном, похожесть = 0.9, не 1.0 — вложение слабее полного совпадения.
# Короче 8 знаков не считаем (иначе «Джаз» совпадёт с «Джаз в усадьбе»), и доля именно 95 %: при 78 % «Вечер
# фортепианной музыки» и «Вечер органной музыки» (разные концерты) выходили 0.7.
CONTAIN_MIN_CHARS = 8
CONTAIN_MIN_SHARE = 0.95
CONTAIN_SCORE = 0.9
# Расхождение времени начала, после которого это два показа в один день, а не один показ с разной записью
# («двери 19:00» и «начало 20:00» — час разницы; дневной детский и вечерний взрослый — 6–7 часов).
TIME_GAP_MIN = 180
# Для выставок и мест время — часы работы, у разных источников они расходятся: время не сравниваем.
TIMELESS_KINDS = frozenset({"выставка", "место"})

# Слова-жанры в начале заголовка: «спектакль «Дюймовочка»» (KudaGo) и «Дюймовочка» (афиша) — одно и то же.
GENRE_PREFIXES: tuple[tuple[str, ...], ...] = tuple(sorted(
    [("мастер", "класс"), ("спектакль",), ("выставка",), ("концерт",), ("фестиваль",), ("лекция",), ("кинопоказ",),
     ("показ",), ("экскурсия",), ("вечеринка",), ("презентация",), ("встреча",), ("шоу",)],
    key=len, reverse=True,
))
# Декоративные слова площадки: «Дом культуры ГЭС-2» и «ГЭС-2» — одно место. Типы вроде «театр», «музей», «клуб»
# не выбрасываем: «Театр Маяковского» и «Музей Маяковского» — разные места.
VENUE_GENERIC = frozenset({"дом", "культуры", "культурный", "центр", "им", "имени", "площадка", "пространство"})

_AGE_RE = re.compile(r"(?<!\d)\d{1,2}\s*\+")
_NON_WORD_RE = re.compile(r"[\W_]+", re.UNICODE)
_TIME_RE = re.compile(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)")

# Поля, по которым считаем заполненность карточки (0 и False — тоже заполнено, пустые строки и списки — нет).
FILL_FIELDS = (
    "venue", "address", "metro", "lat", "lon", "price_from", "price_text", "description", "time_text", "start_time",
    "end_time", "duration_min", "why_fit_hint", "note", "url", "tags", "sources", "rating",
)
FRESHNESS_FIELDS = ("updated_at", "collected_at", "created_at")


# ─── нормализация и триграммы ───

def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").casefold().replace("ё", "е")
    return s


def normalize_title(title: str) -> str:
    """Регистр, ё, кавычки и пунктуация, возрастные метки «16+», пробелы, жанровое слово в начале."""
    tokens = _NON_WORD_RE.sub(" ", _AGE_RE.sub(" ", _fold(title))).split()
    for prefix in GENRE_PREFIXES:
        n = len(prefix)
        if tuple(tokens[:n]) == prefix and len(" ".join(tokens[n:])) >= 3:  # «Концерт» целиком не стираем
            tokens = tokens[n:]
            break
    return " ".join(tokens)


def normalize_venue(venue: str) -> str:
    return " ".join(_NON_WORD_RE.sub(" ", _fold(venue)).split())


def trigrams(text: str) -> frozenset[str]:
    """Как в pg_trgm: каждое слово с двумя пробелами спереди и одним сзади, множество всех троек подряд."""
    grams: set[str] = set()
    for word in text.split():
        padded = f"  {word} "
        grams.update(padded[i:i + 3] for i in range(len(padded) - 2))
    return frozenset(grams)


def trigram_similarity(a: str, b: str) -> float:
    """Жаккар по триграммам нормализованных строк, 0–1."""
    ga, gb = trigrams(a), trigrams(b)
    return len(ga & gb) / len(ga | gb) if ga and gb else 0.0


def title_similarity(a: str, b: str) -> float:
    """Похожесть заголовков 0–1 (на сырых заголовках: нормализация внутри)."""
    return _title_sim(normalize_title(a), normalize_title(b))


def venue_similarity(a: str, b: str) -> float | None:
    """Похожесть площадок 0–1; None — сравнить нельзя (не указана у одной из сторон)."""
    return _venue_sim(_Venue.of(a), _Venue.of(b))


def _title_sim(na: str, nb: str) -> float:
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ga, gb = trigrams(na), trigrams(nb)
    inter = len(ga & gb)
    score = inter / len(ga | gb)
    if min(len(na), len(nb)) >= CONTAIN_MIN_CHARS and inter / min(len(ga), len(gb)) >= CONTAIN_MIN_SHARE:
        score = max(score, CONTAIN_SCORE)
    return score


@dataclass(frozen=True)
class _Venue:
    norm: str
    informative: frozenset[str]  # слова без декоративных
    digits: frozenset[str]       # числа в названии: «Лофт 1» и «Лофт 2» — разные площадки
    grams: frozenset[str]

    @classmethod
    def of(cls, venue: str) -> "_Venue":
        norm = normalize_venue(venue)
        tokens = norm.split()
        informative = frozenset(t for t in tokens if t not in VENUE_GENERIC) or frozenset(tokens)
        return cls(norm, informative, frozenset(t for t in tokens if t.isdigit()), trigrams(norm))


def _venue_sim(a: _Venue, b: _Venue) -> float | None:
    if not a.norm or not b.norm:
        return None
    if a.digits and b.digits and a.digits != b.digits:
        return 0.0
    if a.norm == b.norm:
        return 1.0
    score = len(a.grams & b.grams) / len(a.grams | b.grams)
    short, long_ = sorted((a.informative, b.informative), key=len)
    # Все значимые слова одной площадки есть в другой: «ГЭС-2» внутри «Дом культуры ГЭС-2». Одних цифр мало,
    # нужно слово от 3 букв.
    if short <= long_ and any(len(t) >= 3 and not t.isdigit() for t in short):
        score = 1.0
    return score


# ─── разбор события (EventIn, словарь или объект) ───

def _get(ev: Any, name: str, default: Any = None) -> Any:
    return ev.get(name, default) if isinstance(ev, Mapping) else getattr(ev, name, default)


def _as_date(v: Any) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _start_minutes(ev: Any) -> int | None:
    st = _get(ev, "start_time")
    if isinstance(st, time):
        return st.hour * 60 + st.minute
    m = _TIME_RE.search(st if isinstance(st, str) and st else str(_get(ev, "time_text") or ""))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def _timestamp(ev: Any) -> float | None:
    for name in FRESHNESS_FIELDS:
        v = _get(ev, name)
        if isinstance(v, str):
            try:
                v = datetime.fromisoformat(v)
            except ValueError:
                continue
        if isinstance(v, datetime):
            return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).timestamp()
    return None


def _filled(v: Any) -> bool:
    return v is not None and v != "" and v != [] and v != {} and not (isinstance(v, str) and not v.strip())


@dataclass(frozen=True)
class _Prep:
    title: str
    venue: _Venue
    city: str
    dates: frozenset[date]
    start_min: int | None
    timeless: bool


def _prep(ev: Any) -> _Prep:
    dates = frozenset(d for d in map(_as_date, _get(ev, "dates") or []) if d)
    return _Prep(
        title=normalize_title(str(_get(ev, "title") or "")),
        venue=_Venue.of(str(_get(ev, "venue") or "")),
        city=normalize_venue(str(_get(ev, "city") or "")),
        dates=dates,
        start_min=_start_minutes(ev),
        timeless=_get(ev, "kind") in TIMELESS_KINDS,
    )


# ─── сравнение ───

@dataclass(frozen=True)
class Match:
    """Разбор пары: почему похожи (для подсказки куратору в админке)."""

    score: float
    title: float
    venue: float | None
    shared_dates: tuple[date, ...]
    reason: str  # пусто, если пара не отброшена правилами


def _explain(a: _Prep, b: _Prep) -> Match:
    shared = tuple(sorted(a.dates & b.dates))
    t = _title_sim(a.title, b.title)
    v = _venue_sim(a.venue, b.venue)

    def no(reason: str) -> Match:
        return Match(0.0, t, v, shared, reason)

    if a.city and b.city and a.city != b.city:
        return no("разные города")
    if not shared:
        return no("нет общих дней")
    if t < TITLE_MIN:
        return no("заголовки не похожи")
    if v is not None and v < VENUE_MIN:
        return no("разные площадки")
    if (not a.timeless and not b.timeless and a.start_min is not None and b.start_min is not None
            and abs(a.start_min - b.start_min) >= TIME_GAP_MIN):
        return no("разное время начала в один день")
    score = t * UNKNOWN_VENUE_FACTOR if v is None else TITLE_WEIGHT * t + VENUE_WEIGHT * v
    return Match(min(score, 1.0), t, v, shared, "")


def explain(a: Any, b: Any) -> Match:
    return _explain(_prep(a), _prep(b))


def similarity(a: Any, b: Any) -> float:
    """Похожесть двух событий 0–1. 0 — отброшены правилами (другой город, нет общих дней, другая площадка…)."""
    return explain(a, b).score


def is_duplicate(a: Any, b: Any, threshold: float = DUP_THRESHOLD) -> bool:
    return similarity(a, b) >= threshold


def find_duplicates(events: Sequence[Any], threshold: float = DUP_THRESHOLD) -> list[list[int]]:
    """Группы дубликатов: списки индексов в `events` (по возрастанию), только группы из двух и более.

    Кандидатов ищем через общие дни, остальные пары даже не считаем. Группы связные: если A~B и B~C, то все трое
    в одной группе, даже когда A и C напрямую ниже порога; куратор всё равно смотрит группу целиком.
    """
    preps = [_prep(e) for e in events]
    by_day: dict[date, list[int]] = {}
    for i, p in enumerate(preps):
        for d in p.dates:
            by_day.setdefault(d, []).append(i)
    parent = list(range(len(events)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    seen: set[tuple[int, int]] = set()
    for idxs in by_day.values():
        for pos, i in enumerate(idxs):
            for j in idxs[pos + 1:]:
                if (i, j) in seen:
                    continue
                seen.add((i, j))
                if _explain(preps[i], preps[j]).score >= threshold:
                    parent[find(j)] = find(i)
    groups: dict[int, list[int]] = {}
    for i in range(len(events)):
        groups.setdefault(find(i), []).append(i)
    return sorted((g for g in groups.values() if len(g) > 1), key=lambda g: g[0])


def find_matches(event: Any, candidates: Sequence[Any], threshold: float = DUP_THRESHOLD) -> list[tuple[int, float]]:
    """Новое событие против уже известных (например, выгрузка из базы): [(индекс, похожесть)] по убыванию."""
    p = _prep(event)
    scored = [(i, _explain(p, _prep(c)).score) for i, c in enumerate(candidates)]
    return sorted(((i, s) for i, s in scored if s >= threshold), key=lambda x: (-x[1], x[0]))


# ─── выбор лучшего ───

def completeness(ev: Any) -> int:
    """Сколько полей из FILL_FIELDS заполнено."""
    return sum(_filled(_get(ev, f)) for f in FILL_FIELDS)


def confidence_rank(ev: Any) -> int:
    """подтверждено > вероятно > нужно проверить; неизвестное значение — ниже всех."""
    c = _get(ev, "confidence")
    return len(CONFIDENCE) - CONFIDENCE.index(c) if c in CONFIDENCE else 0


def pick_best(events: Sequence[Any], group: Sequence[int] | None = None) -> int:
    """Индекс «лучшего» в группе: выше уверенность, затем больше заполненных полей, затем свежее.

    «Свежее» — по updated_at / collected_at / created_at, если они есть; у карточек без метки позже в списке значит
    свежее (новую выгрузку принято дописывать в конец). Совсем равные карточки: побеждает более поздняя.
    """
    idxs = list(range(len(events))) if group is None else list(group)
    if not idxs:
        raise ValueError("пустая группа")
    def key(i: int) -> tuple:
        ts = _timestamp(events[i])
        return confidence_rank(events[i]), completeness(events[i]), ts is not None, ts or 0.0, i
    return max(idxs, key=key)
