"""Нормализация без модели: сырая карточка структурированного источника → EventIn детерминированными правилами.

Зачем: ключа OpenRouter может не быть, а лента нужна каждый день. Коллекторы KudaGo, Timepad, Мосбилета, Афиши и
«16 Тонн» берут данные из JSON (API, JSON-LD, серверная выдача Next.js), и всё, что нужно для карточки, уже лежит
в полях RawEvent: даты в `date_text` в нашем же формате, площадка, адрес, координаты, цена, категории источника,
возраст. Этого хватает, чтобы собрать событие правилами; модель остаётся для свободного текста (Telegram, HTML).

Правила честные: ничего не выдумываем. Нет даты — карточка отклоняется (RuleError), нет времени — `time_text` пустой
и confidence ниже, нет площадки — `venue` пустой. Пометка в `note`: первая строка `normalized_by=rules`
(отдельной колонки в Event нет, это зона базы). Статус всегда draft: публикует куратор.

Что делает:
- `parse_date_text`: разбирает `date_text` коллекторов (одиночные показы «YYYY-MM-DD HH:MM–HH:MM», ночные
  «… — …», периоды «период с … по …[, часы …]», у KudaGo ещё «бессрочно», «до …», «с …, дата окончания не указана»,
  несколько показов через «; »). Период проката спектакля — это не расписание: берём ближайшую дату, если она в окне,
  и просим проверить; период выставки — все дни окна, `kind: выставка`.
- `pick_category`: сначала ключевые слова (джаз, волейбол, вино, ИИ, деловые форматы), затем таблица соответствия
  категорий источника нашему каталогу (`core/catalog.ALL_CATS`), иначе «Нетривиальное».
- теги: базовые по категории (`CATEGORY_TAGS`), ключевые по правилам доразметки `seed/retag.py` (как библиотека),
  служебный тег времени по часу начала, `дети` для детских карточек.
- цена, возраст, людно/камерно, описание без служебных строк коллекторов.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta

from leisure.core.catalog import ALL_CATS, CATEGORY_TAGS, KNOWN_TAGS
from leisure.core.timeutil import slot_of
from leisure.normalize.llm import make_slug
from leisure.normalize.schema import EventIn, RawEvent
from leisure.seed.retag import retag_event

MARK = "normalized_by=rules"
RULE_SOURCES: frozenset[str] = frozenset({"kudago", "timepad", "mosbilet", "afisha", "club16tons"})
MAX_DESCRIPTION = 700
MAX_EXHIBITION_DAYS = 400   # «период» длиннее года у не-выставки — явно не расписание, а что-то постоянное
DEFAULT_CATEGORY = "Нетривиальное"


class RuleError(ValueError):
    """Карточку нельзя собрать правилами честно: причина по-русски для сводки конвейера."""


# ─── даты ───

_D = r"(\d{4}-\d{2}-\d{2})"
_T = r"(\d{2}:\d{2})"
_SINGLE_RE = re.compile(rf"^{_D}(?: {_T}(?:–{_T})?)?$")
_OVERNIGHT_RE = re.compile(rf"^{_D} {_T} — {_D} {_T}$")
_PERIOD_RE = re.compile(rf"^период с {_D}(?: {_T})? по {_D}(?: {_T})?(?:, часы {_T}–{_T})?$")
_UNTIL_RE = re.compile(rf"^до {_D}$")
_FROM_RE = re.compile(rf"^с {_D}, дата окончания не указана$")
_MORE_RE = re.compile(r"^… и ещё \d+$")


@dataclass
class Schedule:
    dates: list[date] = field(default_factory=list)
    time_text: str = ""
    kind: str = "событие"
    from_period: bool = False     # даты выведены из периода, а не перечислены источником
    period_end: date | None = None
    mixed_times: list[str] = field(default_factory=list)   # у показов разное время: что ещё встречалось


def _d(s: str) -> date:
    return date.fromisoformat(s)


def _span(t0: str | None, t1: str | None) -> str:
    if not t0:
        return ""
    return f"{t0}–{t1}" if t1 and t1 != t0 else t0


def _days(a: date, b: date) -> list[date]:
    return [a + timedelta(days=i) for i in range((b - a).days + 1)] if b >= a else []


def parse_date_text(date_text: str, date_from: date, date_to: date, *, exhibition: bool = False) -> Schedule:
    """Даты показа в окне [date_from, date_to] из `date_text` коллектора. Непонятный формат или пустое окно → RuleError.

    `exhibition=True` меняет смысл периода: это дни работы выставки, берём все дни окна внутри периода и kind «выставка».
    Иначе период — прокат (спектакль, серия концертов): берём только его первый день, если он в окне.
    """
    text = (date_text or "").strip()
    if not text:
        raise RuleError("нет даты в карточке")
    sched = Schedule()
    times: list[str] = []
    notes: list[str] = []
    for part in [p.strip() for p in text.split(";") if p.strip()]:
        if _MORE_RE.match(part):
            notes.append(part)
            continue
        if m := _SINGLE_RE.match(part):
            day = _d(m.group(1))
            if date_from <= day <= date_to:
                sched.dates.append(day)
                times.append(_span(m.group(2), m.group(3)))
            continue
        if m := _OVERNIGHT_RE.match(part):
            day = _d(m.group(1))
            if date_from <= day <= date_to:
                sched.dates.append(day)
                times.append(f"{m.group(2)} — {m.group(4)}")
            continue
        if m := _PERIOD_RE.match(part):
            start, end = _d(m.group(1)), _d(m.group(3))
            hours = _span(m.group(5), m.group(6)) or _span(m.group(2), m.group(4) if m.group(4) != m.group(2) else None)
            if m.group(5) is None and m.group(2) and m.group(4) and m.group(2) == m.group(4):
                hours = m.group(2)  # «период с D 19:00 по D 19:00»: один и тот же час начала
            _apply_period(sched, start, end, hours, date_from, date_to, exhibition)
            continue
        if m := _UNTIL_RE.match(part):
            _apply_period(sched, date_from, _d(m.group(1)), "", date_from, date_to, exhibition, open_start=True)
            continue
        if m := _FROM_RE.match(part):
            _apply_period(sched, _d(m.group(1)), date_to, "", date_from, date_to, exhibition, open_end=True)
            continue
        if part == "бессрочно":
            _apply_period(sched, date_from, date_to, "", date_from, date_to, exhibition, open_start=True, open_end=True)
            continue
        raise RuleError(f"формат даты не разобран: «{part[:60]}»")
    sched.dates = sorted(set(sched.dates))
    if not sched.dates:
        raise RuleError("ни одной даты в диапазоне сбора")
    if times:
        filled = [t for t in times if t]
        if filled:
            main = max(set(filled), key=filled.count)
            sched.time_text = sched.time_text or main
            sched.mixed_times = sorted(set(filled) - {main})
    return sched


def _apply_period(sched: Schedule, start: date, end: date, hours: str, date_from: date, date_to: date, exhibition: bool,
                  *, open_start: bool = False, open_end: bool = False) -> None:
    sched.from_period = True
    sched.period_end = None if open_end else end
    if exhibition or (end - start).days > MAX_EXHIBITION_DAYS and not open_start:
        sched.kind = "выставка"
        sched.dates += _days(max(start, date_from), min(end, date_to))
        sched.time_text = sched.time_text or hours
        return
    if open_start:
        raise RuleError("период без даты начала: ближайший показ неизвестен")
    if date_from <= start <= date_to:
        sched.dates.append(start)
        sched.time_text = sched.time_text or hours
    # начало проката до окна: ближайший показ в окне источник не назвал, выдумывать не будем (вызывающий получит RuleError)


# ─── категории ───

# Ключевые слова сильнее таблиц источника: «джазовый вечер» в разделе «Концерты» — это Джаз.
KEYWORD_CATEGORIES: tuple[tuple[str, str], ...] = (
    (r"джаз|jazz|блюз|blues", "Джаз"),
    (r"волейбол.*(матч|чемпионат|лига|кубок|против)|(матч|чемпионат|лига|кубок).*волейбол", "Волейбол: матчи"),
    (r"волейбол", "Волейбол"),
    (r"винн(ый|ая|ое|ые|ого|ой)\b|дегустаци\w+ вин|сомелье|энолог", "Винные бары"),
    (r"искусственн\w+ интеллект|нейросет|machine learning|\bml\b|\bai\b|\bии\b|data science|chatgpt|llm", "ИИ и технологии"),
    (r"бизнес-завтрак", "Бизнес-завтраки"),
    (r"конференци|форум\b|саммит|съезд", "Конференции и форумы"),
    (r"предпринимател|нетворкинг|стартап|founders?\b", "Предприниматели и клубы"),
    (r"стратеги|управлен|менеджмент|лидерств|руководител", "Управление и стратегия"),
    (r"мастер-класс|воркшоп|мастерск|своими руками|керамик|гончарн", "Своими руками"),
    (r"усадьб|заповедник|ботаническ|дендрар|\bпарк(?:а|е|у|ом|и|ах|ов)?\b|\bлес[уе]?\b|прогулк", "Природа и усадьбы"),
)

# Категории источников → каталог. Значение None — «это не событие» (аренда, услуга), карточка отклоняется.
SOURCE_CATEGORIES: dict[str, dict[str, str | None]] = {
    "kudago": {  # slug'и категорий событий KudaGo (документация API, event-categories)
        "concert": "Концерты", "theater": "Театр", "exhibition": "Современное искусство", "party": "Вечеринки",
        "cinema": "Кино", "education": DEFAULT_CATEGORY, "kids": DEFAULT_CATEGORY, "festival": "Концерты",
        "quest": DEFAULT_CATEGORY, "business-events": "Конференции и форумы", "stand-up": DEFAULT_CATEGORY,
        "tour": "Природа и усадьбы", "yarmarki-razvlecheniya-yarmarki": DEFAULT_CATEGORY, "recreation": DEFAULT_CATEGORY,
        "entertainment": DEFAULT_CATEGORY, "holiday": DEFAULT_CATEGORY, "social-activity": DEFAULT_CATEGORY,
        "fashion-beauty": DEFAULT_CATEGORY, "photo": "Современное искусство", "other": DEFAULT_CATEGORY,
        "shopping": None, "sales": None, "discounts": None, "speed-dating": "Вечеринки", "evening": "Вечеринки",
    },
    "timepad": {  # названия категорий Timepad
        "Концерты": "Концерты", "Театры": "Театр", "Выставки": "Современное искусство", "Вечеринки": "Вечеринки",
        "Кино": "Кино", "Образование": DEFAULT_CATEGORY, "Лекции": DEFAULT_CATEGORY, "Бизнес": "Предприниматели и клубы",
        "ИТ и интернет": "ИИ и технологии", "Спорт": DEFAULT_CATEGORY, "Экскурсии и путешествия": "Природа и усадьбы",
        "Хобби и творчество": "Своими руками", "Для детей": DEFAULT_CATEGORY, "Еда": DEFAULT_CATEGORY,
        "Психология и самопознание": DEFAULT_CATEGORY, "Наука": DEFAULT_CATEGORY, "Литература": DEFAULT_CATEGORY,
        "Красота и здоровье": DEFAULT_CATEGORY, "Другие развлечения": DEFAULT_CATEGORY, "Другое": DEFAULT_CATEGORY,
    },
    "mosbilet": {  # поле sphere
        "Спектакли": "Театр", "Представления": "Театр", "Концерты": "Концерты", "Выставки": "Современное искусство",
        "Экскурсии": "Природа и усадьбы", "Мастер-классы": "Своими руками", "Лекции": DEFAULT_CATEGORY,
        "Встречи": DEFAULT_CATEGORY, "Для детей": DEFAULT_CATEGORY, "События в парках": "Природа и усадьбы",
        "Зоопарк": "Природа и усадьбы", "Кино": "Кино", "Квесты": DEFAULT_CATEGORY, "Игры": DEFAULT_CATEGORY,
        "Чтения": DEFAULT_CATEGORY, "Досуг": DEFAULT_CATEGORY, "Акции": DEFAULT_CATEGORY, "Фестивали": "Концерты",
        "Дополнительные услуги": None, "Бронирование кортов": None, "Бронирование спортплощадок": None,
    },
    "afisha": {  # подсказка раздела + тип schema.org (collectors/afisha.py)
        "Концерты": "Концерты", "Театр": "Театр", "Выставки": "Современное искусство", "Вечеринки": "Вечеринки",
        "Стендап": DEFAULT_CATEGORY, "Детям": DEFAULT_CATEGORY, "Экскурсии": "Природа и усадьбы",
        "музыка": "Концерты", "театр": "Театр", "выставка": "Современное искусство", "стендап/комедия": DEFAULT_CATEGORY,
        "спорт": DEFAULT_CATEGORY,
    },
    "club16tons": {"Концерты": "Концерты"},
}
EXHIBITION_SOURCE_CATS = frozenset({"exhibition", "Выставки", "выставка", "photo"})
KIDS_SOURCE_CATS = frozenset({"kids", "Для детей", "Детям"})
EXHIBITION_TITLE_RE = re.compile(r"выставк|экспозици", re.IGNORECASE)
LOUD_CATEGORIES = frozenset({"Концерты", "Вечеринки", "Волейбол: матчи", "Конференции и форумы"})

assert all(v in ALL_CATS for m in SOURCE_CATEGORIES.values() for v in m.values() if v is not None)
assert all(c in ALL_CATS for _, c in KEYWORD_CATEGORIES)


def pick_category(raw: RawEvent) -> str:
    """Категория каталога: ключевые слова в названии и первых строках текста, затем таблица источника, иначе «Нетривиальное»."""
    table = SOURCE_CATEGORIES.get(raw.source, {})
    for c in raw.categories:
        if c in table and table[c] is None:
            raise RuleError(f"не событие: категория источника «{c}»")
    haystack = (raw.title + "\n" + raw.text[:400]).lower()
    for pattern, category in KEYWORD_CATEGORIES:
        if re.search(pattern, haystack):
            return category
    for c in raw.categories:
        mapped = table.get(c)
        if mapped and mapped != DEFAULT_CATEGORY:
            return mapped
    return DEFAULT_CATEGORY


def is_exhibition(raw: RawEvent) -> bool:
    return bool(set(raw.categories) & EXHIBITION_SOURCE_CATS) or bool(EXHIBITION_TITLE_RE.search(raw.title))


# ─── остальные поля ───

_MONEY_RE = re.compile(r"₽|руб|р\.|\bот \d")
_FREE_RE = re.compile(r"бесплатн|вход свободн|свободный вход", re.IGNORECASE)
_AGE_RE = re.compile(r"(\d{1,2})\+")
_SERVICE_LINE_RE = re.compile(r"^(Раздел афиши:|Теги KudaGo:|Купить билет$|Для детей\.$|Принимается Пушкинская карта\.$|Вход по регистрации через MosID\.$)")


def price_from(price_text: str) -> int | None:
    """«бесплатно» → 0; «от 600 ₽», «от 600 до 3000 ₽», «1 500 ₽», «от 1200 до 2400 рублей» → минимум; иначе None."""
    if not price_text:
        return None
    if _FREE_RE.search(price_text):
        return 0
    if not _MONEY_RE.search(price_text):
        return None  # числа без рубля («12+», «3 дня») ценой не считаем
    nums = [int(n.replace(" ", "")) for n in re.findall(r"\d[\d ]*", price_text) if n.strip()]
    return min(nums) if nums else None


def audience(raw: RawEvent) -> tuple[bool, bool]:
    """(audience_30plus, audience_kids) по возрастной метке и детским категориям источника; без данных — взрослым, не детям."""
    kids_cat = bool(set(raw.categories) & KIDS_SOURCE_CATS)
    m = _AGE_RE.search(raw.age_restriction or "")
    age = int(m.group(1)) if m else None
    if kids_cat:
        return False, True
    if age is not None and age <= 6:
        return True, True
    return True, False


def clean_description(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines()]
    body = " ".join(ln for ln in lines if ln and not _SERVICE_LINE_RE.match(ln))
    if len(body) > MAX_DESCRIPTION:
        cut = body[:MAX_DESCRIPTION]
        body = (cut.rsplit(". ", 1)[0] + "." if ". " in cut[MAX_DESCRIPTION // 2:] else cut.rsplit(" ", 1)[0] + "…")
    return body


def build_tags(category: str, title: str, description: str, time_text: str, kind: str, kids: bool) -> list[str]:
    """Базовые теги категории, ключевые по правилам retag (как библиотека), служебный тег времени, «дети»."""
    tags = list(CATEGORY_TAGS.get(category, [])[:3])
    ev = {"title": title, "subcategory": "", "description": description, "why_fit_hint": "", "category": category,
          "tags": tags, "audience_kids": kids}
    tags = retag_event(ev)[0]["tags"]
    tags.append(slot_of({"time_text": time_text, "kind": kind}))
    if kids and "дети" not in tags:
        tags.append("дети")
    return [t for t in dict.fromkeys(tags) if t in KNOWN_TAGS]


def normalize_by_rules(raw: RawEvent, date_from: str | date, date_to: str | date) -> EventIn:
    """RawEvent структурированного источника → EventIn (draft, note начинается с `normalized_by=rules`). Иначе RuleError."""
    if raw.source not in RULE_SOURCES:
        raise RuleError(f"источник «{raw.source}» отдаёт свободный текст: нужна LLM-нормализация")
    if not raw.url.startswith(("http://", "https://")):
        raise RuleError("нет ссылки на первоисточник")
    d_from = date.fromisoformat(date_from) if isinstance(date_from, str) else date_from
    d_to = date.fromisoformat(date_to) if isinstance(date_to, str) else date_to
    category = pick_category(raw)
    exhibition = is_exhibition(raw) or category == "Современное искусство" and "период" in raw.date_text
    sched = parse_date_text(raw.date_text, d_from, d_to, exhibition=exhibition)
    adults, kids = audience(raw)
    description = clean_description(raw.text)
    notes = [MARK]
    if sched.from_period and sched.kind != "выставка":
        notes.append(f"источник даёт период проката{f' до {sched.period_end}' if sched.period_end else ''}: взята ближайшая дата, остальные показы по ссылке")
    if sched.mixed_times:
        notes.append("у других показов время: " + ", ".join(sched.mixed_times))
    if "Пушкинская карта" in raw.text:
        notes.append("принимается Пушкинская карта")
    if not raw.venue:
        notes.append("площадка в источнике не названа")
    if not sched.time_text and sched.kind != "выставка":
        notes.append("время начала в источнике не указано")
    if sched.kind == "выставка":
        confidence = "вероятно" if raw.venue else "нужно проверить"
    elif sched.from_period or not raw.venue:
        confidence = "нужно проверить"
    elif sched.time_text:
        confidence = "подтверждено"
    else:
        confidence = "вероятно"
    return EventIn(
        slug=make_slug(raw.title, sched.dates[0].isoformat()),
        title=raw.title[:300],
        category=category,
        kind=sched.kind,
        city="Москва",
        dates=sched.dates,
        time_text=sched.time_text,
        venue=raw.venue or raw.place_name,
        address=raw.address,
        metro=raw.metro,
        lat=raw.lat,
        lon=raw.lon,
        price_from=price_from(raw.price_text),
        price_text=raw.price_text,
        description=description,
        why_fit_hint="",
        note="; ".join(notes),
        tags=build_tags(category, raw.title, description, sched.time_text, sched.kind, kids),
        aesthetics=4 if sched.kind == "выставка" else 3,
        novelty=3,
        crowd="людно" if category in LOUD_CATEGORIES else "камерно",
        audience_30plus=adults,
        audience_kids=kids,
        url=raw.url,
        sources=[raw.url],
        confidence=confidence,
        status="draft",
    )


def can_handle(raw: RawEvent) -> bool:
    return raw.source in RULE_SOURCES


def make_router(llm: Callable[..., EventIn] | None) -> Callable[[RawEvent, str, str], EventIn]:
    """Нормализатор конвейера: структурированные источники правилами, остальные моделью; без модели — честный отказ."""
    def normalize(raw: RawEvent, date_from: str, date_to: str) -> EventIn:
        if can_handle(raw):
            return normalize_by_rules(raw, date_from, date_to)
        if llm is None:
            raise RuleError("нет OPENROUTER_KEY: карточка со свободным текстом ждёт LLM-нормализации")
        return llm(raw, date_from, date_to)
    return normalize


__all__ = ["RULE_SOURCES", "RuleError", "Schedule", "make_router", "normalize_by_rules", "parse_date_text", "pick_category", "price_from"]
