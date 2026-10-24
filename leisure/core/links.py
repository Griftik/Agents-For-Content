"""Ссылки календарей и «Отправить другу» (п. 14 спеки): gcalUrl(), outlookUrl(), shareText(), tgShareUrl() + .ics."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from urllib.parse import urlencode

from .timeutil import DAY_FULL, event_dates, event_times, fmt_date, start_hour, time_text, weekend_title

DEFAULT_CITY = "Москва"
DEFAULT_TZ = "Europe/Moscow"


def event_location(ev: Mapping, city: str = DEFAULT_CITY) -> str:
    parts = [ev.get("venue") or "", ev.get("address") or "", f"м. {ev['metro']}" if ev.get("metro") else ""]
    s = ", ".join(p for p in parts if p)
    return s + (f", {city}" if ev.get("address") else "")


def event_desc(ev: Mapping) -> str:
    parts = [
        ev.get("description") or "",
        f"Цена: {ev['price_text']}" if ev.get("price_text") else "",
        f"Примечание: {ev['note']}" if ev.get("note") else "",
        ev.get("url") or "",
    ]
    return "\n\n".join(p for p in parts if p)


def _gcal_stamp(dt: datetime, all_day: bool) -> str:
    return dt.strftime("%Y%m%d") if all_day else dt.strftime("%Y%m%dT%H%M00")


def gcal_url(ev: Mapping, day: str | None = None, tz: str = DEFAULT_TZ, city: str = DEFAULT_CITY) -> str:
    all_day, start, end = event_times(ev, day)
    q = {
        "action": "TEMPLATE",
        "text": ev.get("title") or "",
        "dates": f"{_gcal_stamp(start, all_day)}/{_gcal_stamp(end, all_day)}",
        "details": event_desc(ev),
        "location": event_location(ev, city),
        "ctz": tz,
    }
    return "https://calendar.google.com/calendar/render?" + urlencode(q)


def outlook_url(ev: Mapping, day: str | None = None, city: str = DEFAULT_CITY) -> str:
    all_day, start, end = event_times(ev, day)
    q = {
        "path": "/calendar/action/compose",
        "rru": "addevent",
        "subject": ev.get("title") or "",
        "startdt": start.strftime("%Y-%m-%dT%H:%M:00"),
        "enddt": end.strftime("%Y-%m-%dT%H:%M:00"),
        "allday": "true" if all_day else "false",
        "location": event_location(ev, city),
        "body": event_desc(ev),
    }
    return "https://outlook.live.com/calendar/0/deeplink/compose?" + urlencode(q)


def share_text(ev: Mapping, day: str | None = None, city: str = DEFAULT_CITY, why: str | None = None) -> str:
    """Текст для друга: название, дата и время, адрес, цена, «почему стоит»."""
    d = day or (event_dates(ev)[0] if event_dates(ev) else "")
    t = time_text(ev)
    when = f"{fmt_date(d) if d else ''}{', ' + t if t else ''}".strip(", ").strip()
    lines = [
        ev.get("title") or "",
        when,
        event_location(ev, city),
        f"Цена: {ev['price_text']}" if ev.get("price_text") else "",
        why or ev.get("why_fit_hint") or ev.get("why_fit") or "",
    ]
    return "\n".join(x for x in lines if x)


def tg_share_url(ev: Mapping, day: str | None = None, url: str | None = None, **kw) -> str:
    """t.me/share: ссылка на публичную страницу события (если передана), иначе на источник."""
    q = {"url": url or ev.get("url") or "", "text": share_text(ev, day, **kw)}
    return "https://t.me/share/url?" + urlencode(q)


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


def _clean_url(u: str) -> str:
    """Только http(s)-ссылка без пробелов и управляющих символов — иначе пусто."""
    u = "".join(ch for ch in str(u) if ch.isprintable() and not ch.isspace())
    return u if u.startswith(("http://", "https://")) else ""


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
