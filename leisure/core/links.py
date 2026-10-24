"""Ссылки календарей и «Отправить другу» (п. 14 спеки): gcalUrl(), outlookUrl(), shareText(), tgShareUrl() + .ics."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from urllib.parse import urlencode, urlparse

from .timeutil import DAY_FULL, event_dates, event_times, fmt_date, start_hour, time_text, weekend_title

DEFAULT_CITY = "Москва"
DEFAULT_TZ = "Europe/Moscow"


def _clean_url(u: str) -> str:
    """Только http(s)-ссылка без пробелов и управляющих символов — иначе пусто."""
    u = "".join(ch for ch in str(u) if ch.isprintable() and not ch.isspace())
    return u if u.startswith(("http://", "https://")) else ""


def event_location(ev: Mapping, city: str = DEFAULT_CITY) -> str:
    parts = [ev.get("venue") or "", ev.get("address") or "", f"м. {ev['metro']}" if ev.get("metro") else ""]
    s = ", ".join(p for p in parts if p)
    return s + (f", {city}" if ev.get("address") else "")


CAL_URL_MAX = 1800  # URL кнопки «Google Календарь» / «Outlook»: описание режем, чтобы влезть (Telegram — до ~2048)


def event_desc(ev: Mapping, desc_limit: int | None = None) -> str:
    """Описание для календаря: текст (описание, цена, примечание) + ссылка на источник. desc_limit режет текст, ссылку — нет."""
    body = "\n\n".join(p for p in (
        ev.get("description") or "",
        f"Цена: {ev['price_text']}" if ev.get("price_text") else "",
        f"Примечание: {ev['note']}" if ev.get("note") else "",
    ) if p)
    if desc_limit is not None and len(body) > desc_limit:
        body = (body[:desc_limit].rstrip() + "…") if desc_limit > 0 else ""
    return "\n\n".join(p for p in (body, _clean_url(ev.get("url") or "")) if p)


def _gcal_stamp(dt: datetime, all_day: bool) -> str:
    return dt.strftime("%Y%m%d") if all_day else dt.strftime("%Y%m%dT%H%M00")


def _fit_description(ev: Mapping, build, max_len: int) -> str:
    """build(desc_limit) → URL. Сокращает текст описания (описание, цена, примечание), пока URL не уложится в max_len (остальное не режем)."""
    url, limit = build(None), len(event_desc(ev))
    while len(url) > max_len and limit > 0:
        limit = int(limit * 0.7) if limit > 40 else 0
        url = build(limit)
    return url


def gcal_url(ev: Mapping, day: str | None = None, tz: str = DEFAULT_TZ, city: str = DEFAULT_CITY,
             max_len: int = CAL_URL_MAX) -> str:
    all_day, start, end = event_times(ev, day)

    def build(limit):
        q = {
            "action": "TEMPLATE",
            "text": ev.get("title") or "",
            "dates": f"{_gcal_stamp(start, all_day)}/{_gcal_stamp(end, all_day)}",
            "details": event_desc(ev, limit),
            "location": event_location(ev, city),
            "ctz": tz,
        }
        return "https://calendar.google.com/calendar/render?" + urlencode(q)

    return _fit_description(ev, build, max_len)


def outlook_url(ev: Mapping, day: str | None = None, city: str = DEFAULT_CITY, max_len: int = CAL_URL_MAX) -> str:
    all_day, start, end = event_times(ev, day)

    def build(limit):
        q = {
            "path": "/calendar/action/compose",
            "rru": "addevent",
            "subject": ev.get("title") or "",
            "startdt": start.strftime("%Y-%m-%dT%H:%M:00"),
            "enddt": end.strftime("%Y-%m-%dT%H:%M:00"),
            "allday": "true" if all_day else "false",
            "location": event_location(ev, city),
            "body": event_desc(ev, limit),
        }
        return "https://outlook.live.com/calendar/0/deeplink/compose?" + urlencode(q)

    return _fit_description(ev, build, max_len)


def is_local_url(url: str) -> bool:
    """localhost / 127.0.0.1 / ::1 — такие адреса Telegram не принимает в URL-кнопках."""
    host = (urlparse(url or "").hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1", "0.0.0.0") or host.endswith(".localhost")


def _share_parts(ev: Mapping, day: str | None, city: str, why: str | None) -> tuple[str, str, str, str, str, str]:
    d = day or (event_dates(ev)[0] if event_dates(ev) else "")
    t = time_text(ev)
    when = f"{fmt_date(d) if d else ''}{', ' + t if t else ''}".strip(", ").strip()
    price = f"Цена: {ev['price_text']}" if ev.get("price_text") else ""
    return (ev.get("title") or "", when, ev.get("venue") or "", event_location(ev, city), price,
            why or ev.get("why_fit_hint") or ev.get("why_fit") or "")


def share_text(ev: Mapping, day: str | None = None, city: str = DEFAULT_CITY, why: str | None = None) -> str:
    """Текст для друга: название, дата и время, адрес, цена, «почему стоит»."""
    title, when, _venue, location, price, hint = _share_parts(ev, day, city, why)
    return "\n".join(x for x in (title, when, location, price, hint) if x)


SHARE_URL_MAX = 1800  # длина всего URL кнопки «Другу»; Telegram на практике принимает до ~2048, держим запас
SHARE_DESC_MAX = 200


def _share_url(url: str, text: str) -> str:
    return "https://t.me/share/url?" + urlencode({"url": url, "text": text})


def tg_share_url(ev: Mapping, day: str | None = None, url: str | None = None, max_len: int = SHARE_URL_MAX,
                 **kw) -> str:
    """t.me/share: ссылка на публичную страницу события (если передана), иначе на источник.

    Кириллица в URL занимает 6 символов на букву, поэтому текст собирается под лимит max_len: сначала название,
    дата и время, площадка; затем, пока влезает, — полный адрес, цена, «почему стоит», описание.
    """
    link = url or ev.get("url") or ""
    title, when, venue, location, price, hint = _share_parts(ev, day, kw.get("city", DEFAULT_CITY), kw.get("why"))
    desc = " ".join((ev.get("description") or "").split())
    if len(desc) > SHARE_DESC_MAX:
        desc = desc[:SHARE_DESC_MAX].rstrip() + "…"

    def fits(lines: list[str]) -> bool:
        return len(_share_url(link, "\n".join(x for x in lines if x))) <= max_len

    lines = [title, when, venue]
    while not fits(lines) and len(title) > 1:  # название длиннее лимита — режем его
        title = title[: max(1, int(len(title) * 0.8))].rstrip() + "…"
        lines[0] = title
    if location and location != venue and fits([title, when, location]):
        lines[2] = location
    for extra in (price, hint, desc):
        if extra and fits(lines + [extra]):
            lines.append(extra)
    return _share_url(link, "\n".join(x for x in lines if x))


def _ics_fold(line: str, limit: int = 75) -> str:
    """RFC 5545: строки не длиннее 75 октетов, продолжение — с пробела; не рвём многобайтовые символы."""
    out, cur, cur_len, first = [], [], 0, True
    for ch in line:
        b = len(ch.encode("utf-8"))
        cap = limit if first else limit - 1
        if cur_len + b > cap:
            out.append("".join(cur))
            cur, cur_len, first = [ch], b, False
        else:
            cur.append(ch)
            cur_len += b
    out.append("".join(cur))
    return "\r\n ".join(out)


def _ics_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def ics_text(ev: Mapping, day: str | None = None, tz: str = DEFAULT_TZ, city: str = DEFAULT_CITY,
             uid_domain: str = "leisure", now: datetime | None = None) -> str:
    """Файл .ics на одно событие (для веба, п. 3.3)."""
    all_day, start, end = event_times(ev, day)
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    uid = f"{ev.get('slug') or ev.get('id') or 'event'}-{start.strftime('%Y%m%d')}@{uid_domain}"
    if all_day:
        dt = [f"DTSTART;VALUE=DATE:{start.strftime('%Y%m%d')}", f"DTEND;VALUE=DATE:{end.strftime('%Y%m%d')}"]
    else:
        dt = [f"DTSTART;TZID={tz}:{start.strftime('%Y%m%dT%H%M%S')}", f"DTEND;TZID={tz}:{end.strftime('%Y%m%dT%H%M%S')}"]
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//leisure//planner//RU", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        "BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{stamp}", *dt,
        f"SUMMARY:{_ics_escape(ev.get('title') or '')}",
        f"LOCATION:{_ics_escape(event_location(ev, city))}",
        f"DESCRIPTION:{_ics_escape(event_desc(ev))}",
    ]
    url = _clean_url(ev.get("url") or "")
    if url:
        lines.append(f"URL:{url}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(_ics_fold(ln) for ln in lines) + "\r\n"


def plan_text(by_day: Mapping[str, Sequence[Mapping]], weekend: Sequence[str],
              horizon: Sequence[Mapping] = ()) -> str:
    """Текст плана (copyPlan() прототипа): по дням, затем «Дальше»."""
    lines = [f"План на {weekend_title(weekend)}"]
    for i, day in enumerate(weekend):
        items = sorted(by_day.get(day, []), key=lambda e: start_hour(time_text(e)) if start_hour(time_text(e)) is not None else 99)
        if not items:
            continue
        lines += ["", f"{DAY_FULL[i] if i < len(DAY_FULL) else day}, {fmt_date(day)}"]
        for ev in items:
            t = time_text(ev)
            line = f"• {t + ' — ' if t else ''}{ev.get('title')} · {ev.get('venue') or ''}"
            if ev.get("address"):
                line += f", {ev['address']}"
            if ev.get("metro"):
                line += f" (м. {ev['metro']})"
            if ev.get("url"):
                line += f" · {ev['url']}"
            lines.append(line)
    if horizon:
        lines += ["", "Дальше"]
        for ev in horizon:
            line = f"• {fmt_date(event_dates(ev)[0])} — {ev.get('title')} · {ev.get('venue') or ''}"
            if ev.get("url"):
                line += f" · {ev['url']}"
            lines.append(line)
    return "\n".join(lines)


def plan_share_url(text: str, url: str, max_len: int = SHARE_URL_MAX) -> str:
    """t.me/share с текстом плана; текст режется по строкам, чтобы URL кнопки не вышел за max_len."""
    lines = text.split("\n")
    while len(lines) > 1 and len(_share_url(url, "\n".join(lines))) > max_len:
        lines.pop()
    out = "\n".join(lines)
    while len(out) > 1 and len(_share_url(url, out)) > max_len:
        out = out[: int(len(out) * 0.9)].rstrip()
    return _share_url(url, out)
