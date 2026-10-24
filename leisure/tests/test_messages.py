"""Тексты и клавиатуры сообщений (web/COPY.md, web/DESIGN.md): заголовок, карточка, план, «Как прошло?»."""
from leisure.bot.callbacks import decision_cb, day_cb, parse_cb, rating_cb, reason_cb
from leisure.worker import messages as m

WEEKEND = ["2026-10-23", "2026-10-24", "2026-10-25"]
EID = "4f2c8a10-1111-2222-3333-444455556666"


def test_callbacks_roundtrip():
    assert parse_cb(decision_cb("иду", EID)) == ("decision", "иду", EID, None)
    assert parse_cb(reason_cb("не в это время", EID)) == ("reason", "не в это время", EID, None)
    assert parse_cb(rating_cb(4, EID)) == ("rating", "4", EID, None)
    assert parse_cb(day_cb(2, EID)) == ("day", "2", EID, None) and parse_cb(f"y:3:{EID}") is None
    assert parse_cb(f"r:m:{EID}").kind == "more_reasons" and parse_cb(f"r:0:{EID}") == ("reason", "", EID, None)
    assert parse_cb("x:y") is None and parse_cb("d:zz:1") is None
    assert all(len(cb.encode()) <= 64 for cb in (decision_cb("интересно", EID, "2026-10-25"), reason_cb("не та компания", EID),
                                                 rating_cb(5, EID), day_cb(1, EID)))


def _item(**over):
    base = {"event": {"id": EID, "title": "Выставка <Хлеб>", "time_text": "11:00–22:00", "venue": "Зотов", "metro": "Улица 1905 года",
                      "price_text": "525 ₽", "free": False, "why_fit_hint": "Конструктивизм и хлеб", "url": "https://x"},
            "day": "2026-10-24", "slot": "день", "score": 83, "days": [],
            "why": [{"t": "Эстетика", "c": ""}, {"t": "нетривиально", "c": ""}, {"t": "выше бюджета", "c": "neg"}],
            "links": {"tg": "https://t.me/share/url?x", "page": "https://example.org/e/hleb", "gcal": "g", "outlook": "o", "ics": "i"},
            "decision": None}
    base.update(over)
    return base


def test_card_text_t_card():
    text = m.card_text(_item(), WEEKEND, plain_links=False)
    assert text.startswith("<b>Выставка &lt;Хлеб&gt;</b>\nСуббота, 24 окт · 11:00–22:00\nЗотов · м. Улица 1905 года\n525 ₽")
    assert "<i>Почему тебе:</i> Эстетика · нетривиально" in text and "<i>Но:</i> выше бюджета" in text
    assert text.endswith("Совпадение 83 %") and "Прежний ответ" not in text


def test_card_text_multiday_prior_answer_and_unparsed_schedule():
    ev = {**_item()["event"], "time_text": "23.10 — 20:00; 24.10 и 25.10 — 17:00 и 20:00"}
    item = _item(event=ev, days=WEEKEND[:3], decision={"status": "иду", "day": "2026-10-24"})
    text = m.card_text(item, WEEKEND, plain_links=False)
    assert "Суббота, 24 окт · 17:00 и 20:00" in text and "Ещё: Пт, 23 окт, Вс, 25 окт" in text
    assert text.endswith("Прежний ответ: иду, суббота")
    odd = _item(event={**ev, "time_text": "сб 21:00; вс 11:30"})
    t2 = m.card_text(odd, WEEKEND, plain_links=False)
    assert "Суббота, 24 окт\n" in t2 and "Расписание: сб 21:00; вс 11:30" in t2


def test_card_keyboard_grid_days_and_marks():
    one = m.card_keyboard(_item(), url_buttons=True)
    assert [[b["text"] for b in r] for r in one] == [["Иду", "Может быть"], ["Интересно", "Мимо"], ["Подробнее", "Другу"]]
    assert one[0][0]["callback_data"] == f"d:g:{EID}:2026-10-24" and one[1][0]["callback_data"] == f"d:i:{EID}:2026-10-24"
    multi = m.card_keyboard(_item(days=WEEKEND[1:], decision={"status": "может", "day": "2026-10-24"}), url_buttons=True)
    assert [b["text"] for b in multi[0]] == ["● Сб", "Вс"] and multi[0][1]["callback_data"] == f"y:2:{EID}"
    assert [b["text"] for b in multi[1]] == ["Иду", "● Может быть"]
    assert all(len(b["callback_data"].encode()) <= 64 for r in multi for b in r if "callback_data" in b)


def test_head_texts_and_keyboards():
    assert "подобрал 5 событий" in m.digest_header("23–25 октября", 5) and "Утром в этот день напомню." in m.digest_header("x", 2)
    assert "вот первая подборка: 3 события" in m.digest_header("x", 3, "Аня", first=True) and "Аня, вот" in m.digest_header("x", 3, "Аня", first=True)
    assert "подходящего немного: 3 события" in m.digest_head_text("x", 3, 0)
    assert "Зато есть 2 события позже" in m.digest_head_text("x", 0, 2)
    assert "ничего не нашлось" in m.digest_head_text("x", 0, 0) and m.digest_head_text("x", 6, 0).startswith("<b>Выходные x</b>\nподобрал 6")
    first = m.digest_head_keyboard("https://w/digest", first=True, url_buttons=True)
    assert [[b["text"] for b in r] for r in first] == [["Весь дайджест", "Мой план"], ["Уточнить под себя"]]
    assert [[b["text"] for b in r] for r in m.digest_head_keyboard("https://w/digest", empty=True, url_buttons=True)] == [["Весь дайджест", "Мои интересы"]]
    assert [[b["callback_data"] for b in r] for r in m.digest_head_keyboard("u", url_buttons=False)] == [["pl:s"]]


def _plan():
    a = {"event": {"id": "a", "title": "А", "time_text": "13:00–15:00", "venue": "V", "address": "A", "metro": "М"}, "status": "иду",
         "conflict": True, "conflict_with": "Б", "day": "2026-10-24", "links": {"gcal": "g", "outlook": "o", "tg": "t"}}
    b = {"event": {"id": "b", "title": "Б", "time_text": "14:00", "venue": "V", "address": "A"}, "status": "иду", "conflict": True,
         "conflict_with": "А", "day": "2026-10-24", "links": {"gcal": "g", "outlook": "o", "tg": "t"}}
    c = {"event": {"id": "c", "title": "В", "time_text": "сб 19:00", "venue": "V", "address": "A"}, "status": "может", "day": "2026-10-24",
         "links": {"gcal": "g", "outlook": "o", "tg": "t"}}
    return {"weekend": WEEKEND, "title": "23–25 октября", "days": {WEEKEND[0]: [], WEEKEND[1]: [a, b, c], WEEKEND[2]: []},
            "horizon": [{"event": {"id": "h", "title": "Выставка", "kind": "выставка", "dates": ["2026-11-20", "2026-11-29"]},
                         "status": "иду", "day": "2026-11-20", "links": {}}]}


def test_plan_overview_card_and_today():
    plan = _plan()
    t = m.plan_overview_text(plan)
    assert t.startswith("<b>План · 23–25 октября</b>\n4 события в плане, одно пересечение.")
    assert "<b>Суббота, 24 окт</b>\n13:00–15:00 · А\n14:00 · Б\nВ (может быть)" in t and "<b>Дальше</b>\nдо 29 ноября · Выставка" in t
    card = m.plan_card_text(plan["days"][WEEKEND[1]][0])
    assert card == ("<b>А</b>\nСуббота, 24 окт · 13:00–15:00\nV, A · м. М\nПересекается по времени с «Б».")
    kb = m.plan_card_keyboard(plan["days"][WEEKEND[1]][0], url_buttons=True)
    assert [b["text"] for b in kb[1]] == ["Другу", "Убрать из плана"] and kb[1][1]["callback_data"] == "d:p:a"
    today = m.plan_today_text(plan, "2026-10-24")
    assert today.startswith("<b>План на сегодня · суббота, 24 окт</b>\n\n<b>А</b>\n13:00–15:00 · V, A\nПересекается по времени с «Б».")
    assert "<b>Б</b>\n14:00 · V, A" in today and "<b>В</b>" not in today and today.endswith("Хорошего дня. Завтра спрошу, как прошло.")
    unknown = {"weekend": WEEKEND, "days": {WEEKEND[1]: [{"event": {"title": "Г", "time_text": "", "venue": "V", "address": "A"}, "status": "иду"}]}}
    assert "Время уточни на странице события · V, A" in m.plan_today_text(unknown, "2026-10-24")
    assert m.plan_today_text(plan, "2026-10-25") == ""
    assert m.plan_empty_text("23–25 октября").startswith("В плане на 23–25 октября пока ничего.")


def test_how_was_it():
    t = m.how_was_it_text({"title": "А"}, "2026-10-24")
    assert t == "<b>Как прошло?</b>\n«А», суббота, 24 окт.\nОцени от 1 до 5: по оценкам я подбираю точнее."
    kb = m.rating_keyboard("e", 4)
    assert [b["text"] for b in kb[0]] == ["1 ★", "2 ★", "3 ★", "4 ★".replace("4", "● 4"), "5 ★"] and kb[1][0]["callback_data"] == "d:p:e"
