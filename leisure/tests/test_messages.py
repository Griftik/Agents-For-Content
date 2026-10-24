from leisure.bot.callbacks import decision_cb, parse_cb, rating_cb, reason_cb
from leisure.worker.messages import card_keyboard, card_text, digest_header, how_was_it_text, plan_today_text, rating_keyboard


def test_callbacks_roundtrip():
    eid = "4f2c8a10-1111-2222-3333-444455556666"
    assert parse_cb(decision_cb("иду", eid)) == ("decision", "иду", eid, None)
    assert parse_cb(reason_cb("не в это время", eid)) == ("reason", "не в это время", eid, None)
    assert parse_cb(rating_cb(4, eid)) == ("rating", "4", eid, None)
    assert parse_cb("x:y") is None and parse_cb("d:zz:1") is None
    assert all(len(cb.encode()) <= 64 for cb in (decision_cb("интересно", eid), reason_cb("не та компания", eid), rating_cb(5, eid)))


def _item():
    return {"event": {"id": "e1", "title": "Выставка <Хлеб>", "time_text": "11:00–22:00", "venue": "Зотов", "metro": "Улица 1905 года",
                      "price_text": "525 ₽", "free": False, "why_fit_hint": "Конструктивизм и хлеб", "url": "https://x"},
            "day": "2026-10-24", "slot": "день", "score": 83,
            "why": [{"t": "Эстетика", "c": ""}, {"t": "нетривиально", "c": ""}, {"t": "выше бюджета", "c": "neg"}],
            "links": {"tg": "https://t.me/share/url?x", "page": "https://example.org/e/hleb", "gcal": "g", "outlook": "o", "ics": "i"}}


def test_card_text_and_keyboard():
    text = card_text(_item(), ["2026-10-23", "2026-10-24", "2026-10-25"])
    assert text.startswith("<b>Выставка &lt;Хлеб&gt;</b>\nСуббота, 24 окт, 11:00–22:00\nЗотов, м. Улица 1905 года\n525 ₽")
    assert "Почему тебе:</i> Эстетика · нетривиально" in text and "Но:</i> выше бюджета" in text and "Совпадение 83%" in text
    kb = card_keyboard(_item())
    assert [b["text"] for b in kb[0]] == ["Иду", "Может быть", "Мимо", "Интересно"] and kb[1][0]["url"] == "https://x"


def test_header_plan_feedback():
    assert "подобрал 5 событий" in digest_header("23–25 октября", 5) and "подобрал 2 события" in digest_header("x", 2)
    plan = {"weekend": ["2026-10-23", "2026-10-24", "2026-10-25"], "days": {"2026-10-24": [
        {"event": {"title": "А", "time_text": "13:00", "venue": "V", "address": "A"}, "status": "иду", "conflict": True},
        {"event": {"title": "Б", "time_text": "19:00", "venue": "V", "address": "A"}, "status": "может"}]}}
    text = plan_today_text(plan, "2026-10-24")
    assert "План на сегодня · Суббота, 24 окт" in text and "13:00 — <b>А</b> ⚠️" in text and "Б" not in text.split("\n")[2]
    assert plan_today_text(plan, "2026-10-25") == ""
    assert "Как прошло?" in how_was_it_text({"title": "А"}) and len(rating_keyboard("e")[0]) == 5
