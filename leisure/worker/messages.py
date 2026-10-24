"""Тексты и клавиатуры Telegram-сообщений: подборка, карточка, план, «Как прошло?». Строки — web/COPY.md, ряды кнопок —
web/DESIGN.md. Только строки и списки кнопок, без сети, чтобы тестировать без бота. Тон — ты-обращение, без эмодзи.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from html import escape

from leisure.api import services
from leisure.bot import keyboards as kb
from leisure.bot.callbacks import decision_cb, day_cb, rating_cb
from leisure.core.links import is_local_url
from leisure.core.timeutil import MONTHS_GEN, event_dates, fmt_date, time_for_day, time_text

Button = dict  # {"text": str, "callback_data": str} | {"text": str, "url": str}
WEEKDAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
DAY_BTN = {4: "Пт", 5: "Сб", 6: "Вс"}
NBSP = " "
STATUS_TITLE = {"иду": "Иду", "может": "Может быть", "интересно": "Интересно", "мимо": "Мимо"}
STATUS_WORD = {"иду": "иду", "может": "может быть", "интересно": "интересно", "мимо": "мимо"}
EMPTY_DIGEST = ("На эти выходные под твой профиль ничего не нашлось. Чаще всего в афише мало событий по твоим направлениям. "
                "Загляни в «Весь дайджест» или добавь направления в /profile. Следующая подборка придёт в четверг.")


def plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n) % 100
    if 11 <= n <= 19:
        return many
    n %= 10
    return one if n == 1 else few if 2 <= n <= 4 else many


_plural = plural


def weekday_label(day: str) -> str:
    """«Суббота, 24 окт»."""
    return f"{WEEKDAYS[date.fromisoformat(day).weekday()]}, {fmt_date(day)}"


def day_phrase(day: str) -> str:
    """«суббота, 24 окт» — в середине фразы."""
    return weekday_label(day).lower()


def weekday_word(day: str) -> str:
    return WEEKDAYS[date.fromisoformat(day).weekday()].lower()


def _day_label(day: str | None, weekend: Sequence[str] = ()) -> str:
    return weekday_label(day) if day else ""


def _event_link(item: Mapping) -> str:
    return item["event"].get("url") or item["links"]["page"]


# ─── заголовок подборки ───
def digest_header(title: str, n_items: int, name: str = "", first: bool = False) -> str:
    """T-DIGEST-HEAD / T-DIGEST-HEAD-FIRST."""
    hello = f"{escape(name)}, " if name else ""
    n = f"{n_items} {plural(n_items, 'событие', 'события', 'событий')}"
    if first:
        return (f"<b>Выходные {escape(title)}</b>\n{hello}вот первая подборка: {n} под твои ценности. Отметь, что подходит, "
                f"и следующие станут точнее.\n\nВремя, бюджет и эстетику можно уточнить кнопкой ниже.")
    return (f"<b>Выходные {escape(title)}</b>\n{hello}подобрал {n} под тебя. Отмечай, что подходит: «Иду» попадёт в план. "
            f"Утром в этот день напомню.")


def digest_head_text(title: str, n_items: int, n_horizon: int, name: str = "", first: bool = False) -> str:
    """Заголовок по составу: обычный, первый, «немного» (1–4) или пустой (T-DIGEST-SHORT, T-DIGEST-EMPTY)."""
    total = n_items + n_horizon
    head = f"<b>Выходные {escape(title)}</b>\n"
    if total == 0:
        return head + EMPTY_DIGEST
    if n_items == 0:
        return (head + f"На эти выходные под твой профиль ничего не нашлось. Зато есть {n_horizon} "
                f"{plural(n_horizon, 'событие', 'события', 'событий')} позже: ниже ближайшие.")
    if not first and total < 5:
        return (head + f"На эти выходные подходящего немного: {total} {plural(total, 'событие', 'события', 'событий')}. "
                f"Остальное в афише слабо совпало с твоими интересами. Шире можно посмотреть в «Весь дайджест» "
                f"или добавить направления в /profile.")
    return digest_header(title, total, name, first)


def digest_head_keyboard(web_url: str, first: bool = False, empty: bool = False, url_buttons: bool | None = None) -> list[list[Button]]:
    if url_buttons is None:
        url_buttons = services.web_links_enabled()
    row = [{"text": "Весь дайджест", "url": web_url}] if url_buttons else []
    row.append({"text": "Мои интересы", "callback_data": "ob:go:i"} if empty else {"text": "Мой план", "callback_data": "pl:s"})
    rows = [row]
    if first and not empty:
        rows.append([{"text": "Уточнить под себя", "callback_data": "ob:go:s"}])
    return rows


# ─── карточка ───
def _prior_answer(item: Mapping) -> str:
    d = item.get("decision")
    if not d or d.get("status") not in STATUS_WORD:
        return ""
    word = STATUS_WORD[d["status"]]
    if d["status"] in ("иду", "может") and d.get("day"):
        word += f", {weekday_word(d['day'])}"
    return f"Прежний ответ: {word}"


def card_text(item: Mapping, weekend: Sequence[str], plain_links: bool | None = None) -> str:
    """T-CARD. plain_links: «Подробнее» и «Другу» текстом (WEB_BASE_URL=localhost, где URL-кнопок нет)."""
    if plain_links is None:
        plain_links = not services.web_links_enabled()
    ev = item["event"]
    day = item.get("day")
    lines = [f"<b>{escape(ev['title'])}</b>"]
    t = time_for_day(ev, day) if day else time_text(ev)
    when = weekday_label(day) if day else ""
    if when or t:
        lines.append(escape(" · ".join(x for x in (when, t) if x)))
    others = [d for d in item.get("days", []) if d != day]
    if day in item.get("days", []) and others:
        lines.append("Ещё: " + escape(", ".join(f"{DAY_BTN[date.fromisoformat(d).weekday()]}, {fmt_date(d)}" for d in others)))
    place = " · ".join(x for x in (ev.get("venue"), f"м. {ev['metro']}" if ev.get("metro") else "") if x)
    if place:
        lines.append(escape(place))
    if day and not t and time_text(ev):
        lines.append(f"Расписание: {escape(time_text(ev))}")
    if ev.get("free"):
        lines.append("Бесплатно")
    elif ev.get("price_text"):
        lines.append(escape(ev["price_text"]))
    why = [w["t"] for w in item.get("why", []) if w.get("c") != "neg"][:3]
    neg = [w["t"] for w in item.get("why", []) if w.get("c") == "neg"]
    if why:
        lines.append(f"<i>Почему тебе:</i> {escape(' · '.join(why))}")
    if ev.get("why_fit_hint"):
        lines.append(escape(ev["why_fit_hint"]))
    if neg:
        lines.append(f"<i>Но:</i> {escape(', '.join(neg))}")
    if item.get("score") is not None:
        lines.append(f"Совпадение {item['score']}{NBSP}%")
    prior = _prior_answer(item)
    if prior:
        lines.append(escape(prior))
    if plain_links:
        lines.append(f"Подробнее: {escape(_event_link(item))}")
        lines.append(f"Другу: {escape(item['links']['tg'])}")
    return "\n".join(lines)


def card_rows(event_id: str, days: Sequence[str], day: str | None, status: str | None,
              reasons: str | None = None, link_rows: list[list[Button]] | None = None) -> list[list[Button]]:
    """Клавиатура карточки: [день] · Иду / Может быть · Интересно / Мимо · [причины] · ссылки.

    День с карточки едет в callback_data решений. reasons: None | 'main' | 'more' (ряды причин «Мимо»).
    """
    def mark(key: str) -> str:
        return ("● " if status == key else "") + STATUS_TITLE[key]

    def dec(key: str) -> Button:
        return {"text": mark(key), "callback_data": decision_cb(key, event_id, day)}

    rows: list[list[Button]] = []
    if len(days) >= 2:
        rows.append([{"text": ("● " if d == day else "") + DAY_BTN[date.fromisoformat(d).weekday()],
                      "callback_data": day_cb(date.fromisoformat(d).weekday() - 4, event_id)} for d in days])
    rows += [[dec("иду"), dec("может")], [dec("интересно"), dec("мимо")]]
    if reasons:
        rows += kb.reasons_keyboard(event_id, more=reasons == "more")
    return rows + (link_rows or [])


def _cap(text: str) -> str:
    """Первая буква заглавная, остальное как есть (str.capitalize портит имена)."""
    return text[:1].upper() + text[1:]


def companions_phrase(names: Sequence[str]) -> str:
    """T-INVITE-TOGETHER: «вдвоём с Имя» (скрытое имя — «вдвоём с другом»), несколько друзей — «с друзьями (n)». Пусто — пустая строка."""
    names = list(names)
    if not names:
        return ""
    if len(names) == 1:
        return f"вдвоём с {names[0]}"
    return f"с друзьями ({len(names)})"


def invite_joined_text(name: str | None, title: str, day: str | None) -> str:
    """T-INVITE-JOINED (бот, пригласивший): «Имя идёт с тобой: «…», суббота, 24 окт.»; скрытое имя — «Друг»."""
    return f"{escape(name or 'Друг')} идёт с тобой: «{escape(title)}»" + (f", {day_phrase(day)}." if day else ".")


def invite_joined_many_text(n: int, title: str, day: str | None) -> str:
    """T-INVITE-JOINED-MANY: сводное, раз в день, без имён."""
    return (f"Ещё {n} {plural(n, 'друг идёт', 'друга идут', 'друзей идут')} с тобой: «{escape(title)}»"
            + (f", {day_phrase(day)}." if day else "."))


def card_link_rows(item: Mapping, url_buttons: bool | None = None) -> list[list[Button]]:
    if url_buttons is None:
        url_buttons = services.web_links_enabled()
    more = _event_link(item)
    row = []
    if url_buttons or not is_local_url(more):
        row.append({"text": "Подробнее", "url": more})
    if url_buttons:
        row.append({"text": "Другу", "url": item["links"]["tg"]})
    return [row] if row else []


def card_keyboard(item: Mapping, url_buttons: bool | None = None, reasons: str | None = None) -> list[list[Button]]:
    d = item.get("decision") or {}
    return card_rows(item["event"]["id"], item.get("days", []), item.get("day"), d.get("status"), reasons,
                     card_link_rows(item, url_buttons))


# ─── план ───
def _event_time(ev: Mapping, day: str) -> str:
    return time_for_day(ev, day)


def _place(ev: Mapping) -> str:
    return ", ".join(x for x in (ev.get("venue"), ev.get("address")) if x)


def plan_overview_text(plan: Mapping) -> str:
    """T-PLAN-HEAD: обычный текст, строки переносятся."""
    days = plan["days"]
    listed = [it for items in days.values() for it in items] + list(plan.get("horizon", []))
    n = len(listed)
    conflicts = sum(1 for items in days.values() for it in items if it.get("conflict")) // 2
    conflicts = max(conflicts, 1) if any(it.get("conflict") for items in days.values() for it in items) else 0
    head = f"<b>План · {escape(plan['title'])}</b>\n{n} {plural(n, 'событие', 'события', 'событий')} в плане"
    if conflicts:
        head += ", одно пересечение" if conflicts == 1 else f", {conflicts} {plural(conflicts, 'пересечение', 'пересечения', 'пересечений')}"
    lines = [head + "."]
    for day in plan["weekend"]:
        items = sorted(days.get(day, []), key=lambda it: (it["status"] != "иду", ))
        if not items:
            continue
        lines += ["", f"<b>{escape(weekday_label(day))}</b>"]
        for it in items:
            t = _event_time(it["event"], day)
            maybe = " (может быть)" if it["status"] == "может" else ""
            with_ = f" · {companions_phrase(it.get('companions') or [])}" if it.get("companions") else ""
            lines.append(escape((t + " · " if t else "") + it["event"]["title"] + maybe + with_))
    horizon = list(plan.get("horizon", []))
    if horizon:
        lines += ["", "<b>Дальше</b>"]
        for it in horizon:
            ds = event_dates(it["event"])
            if it["event"].get("kind") in ("выставка", "место") and ds:
                d = date.fromisoformat(ds[-1])
                when = f"до {d.day} {MONTHS_GEN[d.month - 1]}"
            else:
                when = fmt_date(it.get("day") or ds[0])
            maybe = " (может быть)" if it["status"] == "может" else ""
            lines.append(escape(f"{when} · {it['event']['title']}{maybe}"))
    return "\n".join(lines)


def plan_empty_text(title: str) -> str:
    return f"В плане на {escape(title)} пока ничего. Отметь «Иду» у событий в подборке, и они появятся здесь: /digest."


def plan_card_text(it: Mapping, day: str | None = None) -> str:
    """T-PLAN-CARD."""
    ev = it["event"]
    day = day or it.get("day")
    t = _event_time(ev, day) if day else ""
    lines = [f"<b>{escape(ev['title'])}</b>"]
    when = " · ".join(x for x in (weekday_label(day) if day else "", t) if x)
    if when:
        lines.append(escape(when))
    place = ", ".join(x for x in (ev.get("venue"), ev.get("address")) if x)
    if ev.get("metro"):
        place += f" · м. {ev['metro']}" if place else f"м. {ev['metro']}"
    if place:
        lines.append(escape(place))
    if it.get("companions"):
        lines.append(escape(_cap(companions_phrase(it["companions"])) + "."))
    if it.get("conflict"):
        other = it.get("conflict_with")
        lines.append(f"Пересекается по времени с «{escape(other)}»." if other else "Пересекается по времени.")
    return "\n".join(lines)


PLAN_CARDS_MAX = 6


def plan_card_keyboard(it: Mapping, url_buttons: bool | None = None) -> list[list[Button]]:
    if url_buttons is None:
        url_buttons = services.web_links_enabled()
    rows = [[{"text": "Google Календарь", "url": it["links"]["gcal"]}, {"text": "Outlook", "url": it["links"]["outlook"]}]]
    last = []
    if url_buttons:
        last.append({"text": "Другу", "url": it["links"]["tg"]})
    last.append({"text": "Убрать из плана", "callback_data": decision_cb("пропуск", it["event"]["id"])})
    return rows + [last]


def plan_item_keyboard(item: Mapping, url_buttons: bool | None = None) -> list[list[Button]]:
    """Календарные кнопки под событием в «Плане на сегодня»."""
    if url_buttons is None:
        url_buttons = services.web_links_enabled()
    rows = [[{"text": "Google Календарь", "url": item["links"]["gcal"]}, {"text": "Outlook", "url": item["links"]["outlook"]}]]
    if url_buttons:
        rows.append([{"text": "Другу", "url": item["links"]["tg"]}])
    return rows


def plan_today_text(plan: Mapping, day: str) -> str:
    """T-PLAN-TODAY."""
    items = [it for it in plan["days"].get(day, []) if it["status"] == "иду"]
    if not items:
        return ""
    lines = [f"<b>План на сегодня · {escape(day_phrase(day))}</b>"]
    for it in items:
        ev = it["event"]
        t = _event_time(ev, day)
        place = _place(ev)
        lines += ["", f"<b>{escape(ev['title'])}</b>",
                  escape(f"{t} · {place}" if t else f"Время уточни на странице события · {place}")]
        if it.get("companions"):
            lines.append(escape(_cap(companions_phrase(it["companions"])) + "."))
        if it.get("conflict"):
            other = it.get("conflict_with")
            lines.append(f"Пересекается по времени с «{escape(other)}»." if other else "Пересекается по времени.")
    lines += ["", "Хорошего дня. Завтра спрошу, как прошло."]
    return "\n".join(lines)


# ─── «Как прошло?» ───
def how_was_it_text(ev: Mapping, day: str | None = None) -> str:
    when = f", {day_phrase(day)}" if day else ""
    return f"<b>Как прошло?</b>\n«{escape(ev['title'])}»{when}.\nОцени от 1 до 5: по оценкам я подбираю точнее."


def rating_keyboard(event_id: str, rating: int | None = None) -> list[list[Button]]:
    return [[{"text": ("● " if rating == n else "") + f"{n} ★", "callback_data": rating_cb(n, event_id)} for n in range(1, 6)],
            [{"text": "Не получилось пойти", "callback_data": decision_cb("пропуск", event_id)}]]
