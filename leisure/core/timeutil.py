"""Время, слоты, уикенд, цена. Перенос slotOf(), recoSlot(), isFree(), WEEKEND и evTimes() из прототипа."""
from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta

MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
              "сентября", "октября", "ноября", "декабря"]
DAY_SHORT = ["Пт", "Сб", "Вс"]
DAY_FULL = ["Пятница", "Суббота", "Воскресенье"]
DEFAULT_DURATION_MIN = 150

_TOKEN_RE = re.compile(r"(?<!\d)(\d{1,2})([:.])(\d{2})(?!\d)")
_DASH_RE = re.compile(r"^\s*[–—-]\s*$")
_FREE_RE = re.compile(r"бесплатн|вход свободн|свободный вход")
_MONEY_RE = re.compile(r"\d\s?₽|руб")


def time_text(ev: Mapping) -> str:
    """Поле времени: `time_text` по спеке, `time` — как в прототипе."""
    return str(ev.get("time_text") or ev.get("time") or "")


def time_tokens(t: str | None) -> list[tuple[float, str, int, int]]:
    """Отметки времени в тексте: (час с долей, разделитель, начало, конец).

    Берём только правдоподобные (час ≤ 23, минуты ≤ 59); если есть хоть одна с двоеточием —
    отметки с точкой считаем датами («23.10 — 20:00») и отбрасываем.
    """
    out = []
    for m in _TOKEN_RE.finditer(t or ""):
        h, sep, mi = int(m.group(1)), m.group(2), int(m.group(3))
        if h <= 23 and mi <= 59:
            out.append((h + mi / 60, sep, m.start(), m.end()))
    if any(sep == ":" for _, sep, _, _ in out):
        out = [x for x in out if x[1] == ":"]
    return out


_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})\.(\d{2})(?![\d:])")
_DATES_RE = re.compile(r"\(?\s*\d{1,2}\.\d{2}(?:\s*(?:,|и)\s*\d{1,2}\.\d{2})*\s*\)?")
_WEEKDAY_RE = re.compile(r"(?<![а-яё])(пн|вт|ср|чт|пт|сб|вс)(?![а-яё])")


def _segment_dates(seg: str) -> set[str]:
    return {f"{int(d):02d}.{m}" for d, m in _DATE_RE.findall(seg) if 1 <= int(m) <= 12 and 1 <= int(d) <= 31}


def time_for_day(ev: Mapping, day: str) -> str:
    """Время события в выбранный день из `time_text`: «17:00 и 20:00». Пусто, если разобрать нельзя.

    Понимает расписание по датам («23.10 — 20:00; 24.10 и 25.10 — 17:00 и 20:00», «20:00 (23.10) / 19:00 (24.10)»).
    Без дат — весь текст, если в нём есть время. Расписание по дням недели («сб 21:00; вс 11:30») не разбираем.
    """
    text = time_text(ev).strip()
    if not time_tokens(text):
        return ""
    segs = [x.strip() for x in re.split(r";| / ", text) if x.strip()]
    dated = [(s, _segment_dates(s)) for s in segs]
    if any(ds for _, ds in dated):
        d = date.fromisoformat(str(day)[:10])
        key = f"{d.day:02d}.{d.month:02d}"
        parts = []
        for seg, ds in dated:
            if key not in ds:
                continue
            if "также" in seg:
                return ""
            clean = _DATES_RE.sub("", seg).strip()
            clean = re.sub(r"^[\s–—-]+|[\s–—-]+$", "", clean).strip()
            if clean and time_tokens(clean):
                parts.append(clean)
        return " и ".join(parts)
    if _WEEKDAY_RE.search(text):
        return ""
    return text


def start_hour(t: str | None) -> float | None:
    tk = time_tokens(t)
    return tk[0][0] if tk else None


def end_hour(ev: Mapping) -> float | None:
    """Конец: вторая отметка, если она идёт сразу за первой через тире («19:00–21:00»), иначе старт + длительность."""
    t = time_text(ev)
    tk = time_tokens(t)
    if len(tk) >= 2 and _DASH_RE.match(t[tk[0][3]:tk[1][2]]):
        return tk[1][0]
    if not tk:
        return None
    return tk[0][0] + (ev.get("duration_min") or DEFAULT_DURATION_MIN) / 60


def hhmm(h: float | None) -> str | None:
    """19.5 → '19:30' (для start_time/end_time в БД)."""
    if h is None:
        return None
    minutes = int(round(h * 60)) % (24 * 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def slot_of(ev: Mapping) -> str:
    """утро / день / вечер / ночь. Выставки всегда «день», места — по часу открытия."""
    h = start_hour(time_text(ev))
    kind = ev.get("kind")
    if kind == "выставка":
        return "день"
    if kind == "место":
        return "день" if (h is not None and h < 16) else "вечер"
    if h is None:
        return "день"
    if h < 12:
        return "утро"
    if h < 17:
        return "день"
    if h < 22:
        return "вечер"
    return "ночь"


def reco_slot(ev: Mapping) -> str:
    """Слот рекомендации: утро сливается с днём, ночь — с вечером."""
    s = slot_of(ev)
    return "день" if s == "утро" else "вечер" if s == "ночь" else s


def iso(d: date) -> str:
    return d.isoformat()


def weekend_for(today: date) -> list[date]:
    """[пт, сб, вс] ближайшего уикенда: в сб/вс — текущий, иначе предстоящий (в пятницу — сегодняшний)."""
    wd = today.weekday()  # пн=0 … вс=6
    if wd == 5:
        fri = today - timedelta(days=1)
    elif wd == 6:
        fri = today - timedelta(days=2)
    else:
        fri = today + timedelta(days=4 - wd)
    return [fri + timedelta(days=i) for i in range(3)]


def weekend_iso(today: date) -> list[str]:
    return [iso(d) for d in weekend_for(today)]


def weekend_title(weekend: Sequence[str]) -> str:
    """«23–25 октября» или «30 октября – 1 ноября»."""
    a, b = date.fromisoformat(weekend[0]), date.fromisoformat(weekend[-1])
    if a.month == b.month:
        return f"{a.day}–{b.day} {MONTHS_GEN[a.month - 1]}"
    return f"{a.day} {MONTHS_GEN[a.month - 1]} – {b.day} {MONTHS_GEN[b.month - 1]}"


WEEKDAYS_RU = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]


def day_phrase(iso_s: str) -> str:
    """«суббота, 24 окт»."""
    d = date.fromisoformat(str(iso_s)[:10])
    return f"{WEEKDAYS_RU[d.weekday()]}, {d.day} {MONTHS[d.month - 1]}"


def fmt_date(iso_s: str) -> str:
    d = date.fromisoformat(str(iso_s)[:10])
    return f"{d.day} {MONTHS[d.month - 1]}"


def event_dates(ev: Mapping) -> list[str]:
    return [str(d)[:10] for d in (ev.get("dates") or [])]


def weekend_days(ev: Mapping, weekend: Sequence[str]) -> list[str]:
    wk = set(weekend)
    return [d for d in event_dates(ev) if d in wk]


def is_horizon(ev: Mapping, weekend: Sequence[str]) -> bool:
    """Событие дальше этих выходных (покупается заранее)."""
    return not weekend_days(ev, weekend)


LEAD_MIN = 30                      # событие попадает в подборку на сегодня, если начинается не раньше now + 30 минут (время доехать)
OPEN_KINDS = ("выставка", "место")  # работают в течение дня: прячем только после окончания (end_time), а не после начала


def _minutes(t) -> int | None:
    """'HH:MM[:SS]' или time → минуты от полуночи; пусто или мусор — None."""
    if not t:
        return None
    if isinstance(t, str):
        try:
            h, m = t.split(":")[:2]
            return int(h) * 60 + int(m)
        except ValueError:
            return None
    return t.hour * 60 + t.minute


def _gone_today(ev: Mapping, now_min: int) -> bool:
    """Сегодняшняя дата события уже не годится для подборки: началось или начнётся меньше чем через LEAD_MIN минут;
    для выставок и мест — только если end_time уже прошёл."""
    if ev.get("kind") in OPEN_KINDS:
        end = _minutes(ev.get("end_time"))
        return end is not None and now_min >= end
    start = _minutes(ev.get("start_time"))
    return start is not None and start < now_min + LEAD_MIN


def trim_past(events: Iterable[Mapping], today_iso: str, now: datetime | None = None) -> list[dict]:
    """Как в прототипе: прошедшие даты выкидываем, события без будущих дат — целиком.

    now — местное время (используются только дата и часы). Если дата now совпадает с today_iso, то «сегодня» у события,
    которое по start_time начинается раньше now + LEAD_MIN, тоже выкидывается (см. _gone_today). Без now — по дате.
    """
    now_min = now.hour * 60 + now.minute if now is not None and now.date().isoformat() == today_iso else None
    out: list[dict] = []
    for ev in events:
        ds = [d for d in event_dates(ev) if d >= today_iso]
        if now_min is not None and today_iso in ds and _gone_today(ev, now_min):
            ds = [d for d in ds if d != today_iso]
        if not ds:
            continue
        e = dict(ev)
        e["dates"] = ds
        out.append(e)
    return out


def price_num(ev: Mapping) -> int | float | None:
    p = ev.get("price_from")
    return p if isinstance(p, (int, float)) and not isinstance(p, bool) else None


def is_free(ev: Mapping) -> bool:
    """Бесплатно = явный 0 или обещание свободного входа без суммы в рублях перед ним."""
    if price_num(ev) == 0:
        return True
    t = str(ev.get("price_text") or "").lower()
    if not _FREE_RE.search(t):
        return False
    head = _FREE_RE.split(t)[0]
    return not _MONEY_RE.search(head)


def event_times(ev: Mapping, day: str | None = None) -> tuple[bool, datetime, datetime]:
    """(all_day, start, end) в локальном времени города — для ссылок календаря и .ics."""
    st = start_hour(time_text(ev))
    en = end_hour(ev)
    d0 = date.fromisoformat(str(day or event_dates(ev)[0])[:10])
    base = datetime(d0.year, d0.month, d0.day)
    if st is None:
        return True, base, base + timedelta(days=1)

    def mk(h: float) -> datetime:
        return base + timedelta(minutes=int(round(h * 60)))

    start = mk(st)
    end = mk(en if en is not None else st + 2)
    if end <= start:
        end += timedelta(days=1)
    return False, start, end


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def js_round(x: float) -> int:
    """Math.round из JS: половины — вверх (в Python round() — к чётному)."""
    return int(math.floor(x + 0.5))
