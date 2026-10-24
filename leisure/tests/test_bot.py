"""Бот: чистые функции клавиатур и онбординга, сборка диспетчера, профильный текст."""
from leisure.bot import keyboards as kb
from leisure.bot.callbacks import parse_cb
from leisure.bot.commands import profile_text
from leisure.core.catalog import ALL_CATS, VALUES

from .conftest import fresh_dispatcher


def test_values_keyboard_progress_and_next():
    rows = kb.values_pick_keyboard([])
    assert rows[-1][0]["text"] == "Выбрано 0 из 5" and sum(len(r) for r in rows[:-1]) == len(VALUES)
    five = VALUES[:5]
    rows = kb.values_pick_keyboard(five)
    assert rows[-1][0]["callback_data"] == "ob:vnext" and rows[0][0]["text"].startswith("✓ ")
    assert all(len(b["callback_data"].encode()) <= 64 for r in rows for b in r)


def test_weights_from_choice():
    w = kb.weights_from_choice(VALUES[:5], ["Свобода"])
    assert all(w[v] == 5 for v in VALUES[:5]) and w["Свобода"] == 3 and w["Природа"] == 1 and set(w) == set(VALUES)


def test_interests_keyboard_labels():
    rows = kb.interests_keyboard({"Джаз": 3, "Кино": 0})
    texts = [b["text"] for r in rows for b in r]
    assert "Джаз · в первую очередь" in texts and "Кино · —" in texts and texts[-1] == "Готово →"
    assert len(rows) == len(ALL_CATS) + 1


def test_mark_keyboard_moves_dot():
    rows = [[{"text": "● Иду", "callback_data": "d:g:x"}, {"text": "Может быть", "callback_data": "d:m:x"}, {"text": "Мимо", "callback_data": "d:s:x"}],
            [{"text": "Подробнее", "url": "https://x"}]]
    out = kb.mark_keyboard(rows, "Мимо")
    assert [b["text"] for b in out[0]] == ["Иду", "Может быть", "● Мимо"] and out[1][0]["url"] == "https://x"
    assert [b["text"] for b in kb.mark_keyboard(out, None)[0]] == ["Иду", "Может быть", "Мимо"]


def test_reasons_keyboard_roundtrip():
    rows = kb.reasons_keyboard("e1")
    cbs = [b["callback_data"] for r in rows for b in r]
    assert rows[0][0]["text"] == kb.REASON_CAPTION and cbs[0] == "ob:noop"
    assert parse_cb(cbs[1]) == ("reason", "не моё", "e1", None) and cbs[-1] == "r:0:e1"


def test_dispatcher_builds():
    dp = fresh_dispatcher()
    assert {r.name for r in dp.sub_routers} == {"onboarding", "decisions", "commands", "fallback"}


def test_profile_text():
    v = {"values": {v: 1 for v in VALUES} | {"Творчество": 5, "Природа": 5}, "interests": {"Джаз": 3, "Вечеринки": 0},
         "params": {"company": "вдвоём", "times": ["вечер"], "budget": 2500, "aesthetics": True},
         "learned_text": "чаще выбираешь: музыка"}
    t = profile_text(v)
    assert "Творчество" in t and "В первую очередь:</b> Джаз" in t and "Не показываю:</b> Вечеринки" in t and "бюджет 2500" in t
