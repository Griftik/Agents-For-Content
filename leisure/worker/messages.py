"""Тексты и клавиатуры Telegram-сообщений (п. 3.2–3.4 спеки): дайджест, «План на сегодня», «Как прошло?».

Только строки и списки кнопок — без сети, чтобы тестировать без бота. Тон — ты-обращение, как в прототипе.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from html import escape

from leisure.bot.callbacks import decision_cb, rating_cb
from leisure.core.timeutil import DAY_FULL, fmt_date, time_text

Button = dict  # {"text": str, "callback_data": str} | {"text": str, "url": str}


def _day_label(day: str | None, weekend: Sequence[str]) -> str:
    if not day:
        return ""
    if day in weekend:
        return f"{DAY_FULL[weekend.index(day)]}, {fmt_date(day)}"
    return fmt_date(day)


def digest_header(title: str, n_items: int, name: str = "") -> str:
    hello = f"{escape(name)}, " if name else ""
    return (f"<b>Выходные {escape(title)}</b>\n{hello}подобрал {n_items} {_plural(n_items, 'событие', 'события', 'событий')} под тебя. "
            f"Отмечай «Иду» — соберу план и напомню в субботу утром.")


def _plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n) % 100
    if 11 <= n <= 19:
        return many
    n %= 10
    return one if n == 1 else few if 2 <= n <= 4 else many


def card_text(item: Mapping, weekend: Sequence[str]) -> str:
    ev = item["event"]
    lines = [f"<b>{escape(ev['title'])}</b>"]
    when = _day_label(item.get("day"), weekend)
    t = time_text(ev)
    if when or t:
        lines.append(escape(", ".join(x for x in (when, t) if x)))
    place = ", ".join(x for x in (ev.get("venue"), f"м. {ev['metro']}" if ev.get("metro") else "") if x)
    if place:
        lines.append(escape(place))
    if ev.get("free"):
        lines.append("Бесплатно")
    elif ev.get("price_text"):
        lines.append(escape(ev["price_text"]))
    why = [w["t"] for w in item.get("why", []) if w.get("c") != "neg"][:3]
    neg = [w["t"] for w in item.get("why", []) if w.get("c") == "neg"]
    hint = ev.get("why_fit_hint")
    if why:
        lines.append(f"<i>Почему тебе:</i> {escape(' · '.join(why))}")
    if hint:
        lines.append(escape(hint))
    if neg:
        lines.append(f"<i>Но:</i> {escape(', '.join(neg))}")
    if item.get("score") is not None:
        lines.append(f"Совпадение {item['score']}%")
    return "\n".join(lines)


def card_keyboard(item: Mapping) -> list[list[Button]]:
    eid = item["event"]["id"]
    row1 = [{"text": "Иду", "callback_data": decision_cb("иду", eid)},
            {"text": "Может быть", "callback_data": decision_cb("может", eid)},
            {"text": "Мимо", "callback_data": decision_cb("мимо", eid)}]
    row2 = [{"text": "Подробнее", "url": item["event"].get("url") or item["links"]["page"]},
            {"text": "Другу", "url": item["links"]["tg"]}]
    return [row1, row2]


def digest_footer_keyboard(web_url: str) -> list[list[Button]]:
    return [[{"text": "Весь дайджест", "url": web_url}]]


def plan_today_text(plan: Mapping, day: str) -> str:
    items = [it for it in plan["days"].get(day, []) if it["status"] == "иду"]
    if not items:
        return ""
    label = _day_label(day, plan["weekend"])
    lines = [f"<b>План на сегодня · {escape(label)}</b>"]
    for it in items:
        ev = it["event"]
        t = time_text(ev)
        place = ", ".join(x for x in (ev.get("venue"), ev.get("address")) if x)
        warn = " ⚠️ пересекается по времени" if it.get("conflict") else ""
        lines.append(f"• {escape(t + ' — ' if t else '')}<b>{escape(ev['title'])}</b>{warn}\n  {escape(place)}")
    lines.append("Хорошего дня. В понедельник спрошу, как прошло.")
    return "\n".join(lines)


def plan_item_keyboard(item: Mapping) -> list[list[Button]]:
    return [[{"text": "Google Календарь", "url": item["links"]["gcal"]}, {"text": "Outlook", "url": item["links"]["outlook"]}],
            [{"text": "Другу", "url": item["links"]["tg"]}]]


def how_was_it_text(ev: Mapping) -> str:
    return f"Как прошло?\n<b>{escape(ev['title'])}</b>\nОцени от 1 до 5 — это лучше всего учит подборку."


def rating_keyboard(event_id: str) -> list[list[Button]]:
    return [[{"text": "★" * n, "callback_data": rating_cb(n, event_id)} for n in range(1, 6)]]
