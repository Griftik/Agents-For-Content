"""Бот: чистые функции клавиатур и экранов онбординга, сборка диспетчера, тексты профиля и справочные функции."""
import pytest

from leisure.bot import keyboards as kb
from leisure.bot import texts
from leisure.bot.callbacks import parse_cb
from leisure.core.catalog import (ALL_CATS, VALUES, cat_label, default_profile, interests_from_values, propose_interests,
                                  proposed_categories, rank_categories, weights_from_top)

from .conftest import fresh_dispatcher


def test_weights_from_top_five_and_neutral_rest():
    w = weights_from_top(VALUES[:5])
    assert all(w[v] == 5 for v in VALUES[:5]) and all(w[v] == 2 for v in VALUES[5:]) and set(w) == set(VALUES)


def test_propose_interests_two_three_four_two_rest_one_never_zero():
    for vals in (default_profile()["values"], weights_from_top(["Покой", "Азарт", "Веселье", "Близость", "Удовольствие"]),
                 weights_from_top(VALUES[:5])):
        lv = propose_interests(vals)
        assert sorted(lv.values(), reverse=True) == [3, 3, 2, 2, 2, 2] + [1] * 13 and 0 not in lv.values()
        ranked = rank_categories(vals)
        assert [lv[c] for c in ranked[:2]] == [3, 3] and proposed_categories(vals) == ranked[:6]
    flat = propose_interests({v: 2 for v in VALUES})                      # при равенстве меры — порядок ALL_CATS
    assert sorted(flat.values(), reverse=True)[:6] == [3, 3, 2, 2, 2, 2] and [c for c, x in flat.items() if x == 3] == ALL_CATS[:2]


def test_cat_labels_fit_a_row_of_two():
    assert cat_label("Джаз") == "Джаз" and cat_label("Природа и усадьбы") == "Природа и усадьбы"
    assert cat_label("Современное искусство") == "Совр. искусство" and cat_label("Предприниматели и клубы") == "Бизнес-клубы"
    assert cat_label("Образование для управленцев") == "Для управленцев" and cat_label("Управление и стратегия") == "Стратегия"
    assert all(len(cat_label(c)) <= 17 for c in ALL_CATS)


def test_interests_main_and_all_keyboards():
    levels = {c: 1 for c in ALL_CATS} | {"Театр": 3, "Джаз": 2, "Кино": 0}
    main = kb.interests_main_keyboard(["Театр", "Джаз", "Кино"], levels, 16)
    assert [b["text"] for b in main[0]] == ["✓✓ Театр", "✓ Джаз"] and main[1][0]["text"] == "— Кино"
    assert [r[0]["text"] for r in main[-3:]] == ["Все направления (16)", "Показать подборку →", "← Назад"]
    allk = kb.interests_all_keyboard(levels, 3)
    assert [b["text"] for b in allk[0]] == ["Не показывать", "Иногда"] and [b["text"] for b in allk[1]] == ["Интересно", "● В первую очередь"]
    cats = [b for r in allk[2:-2] for b in r]
    assert len(cats) == 19 and allk[2][0]["callback_data"] == "ob:cs:0:3" and "Для управленцев" in [b["text"] for b in cats]
    assert len(allk) == 2 + 10 + 2 and allk[-1][0]["text"] == "← К шести"
    assert all(len(b["callback_data"].encode()) <= 64 for r in allk for b in r)


def test_setup_menu_shows_values_and_hides_district():
    rows = kb.setup_menu_keyboard({"budget": 2500, "aesthetics": False, "times": ["вечер"], "company": "любая"}, False)
    assert [r[0]["text"] for r in rows] == ["Бюджет · до 2 500 ₽", "Эстетика · не принципиальна", "Время · вечер", "С детьми · нет",
                                            "Заметка · нет", "Готово"]
    assert "Район" not in str(rows) and "Компания" not in str(rows)
    assert rows[3][0]["callback_data"] == "ob:go:sc" and rows[4][0]["callback_data"] == "ob:go:n"
    assert [r[0]["text"] for r in kb.setup_menu_keyboard({}, True, dirty=True)][-3:] == ["Заметка · есть", "Пересобрать подборку", "Готово"]


def test_reasons_keyboard_two_steps():
    rows = kb.reasons_keyboard("e1")
    assert rows[0][0]["text"] == kb.REASON_CAPTION and rows[0][0]["callback_data"] == "ob:noop"
    assert [b["text"] for b in rows[1]] == ["Не моё", "Дорого", "Далеко", "Ещё…"]
    assert parse_cb(rows[1][0]["callback_data"]) == ("reason", "не моё", "e1", None) and parse_cb(rows[1][3]["callback_data"]).kind == "more_reasons"
    more = kb.reasons_keyboard("e1", more=True)
    assert [[b["text"] for b in r] for r in more[1:]] == [["Уже был", "Не то время"], ["Не та компания"]]
    assert parse_cb(more[1][1]["callback_data"]) == ("reason", "не в это время", "e1", None)


def test_mark_keyboard_moves_dot():
    rows = [[{"text": "● Иду", "callback_data": "d:g:x"}, {"text": "Может быть", "callback_data": "d:m:x"}, {"text": "Мимо", "callback_data": "d:s:x"}],
            [{"text": "Подробнее", "url": "https://x"}]]
    out = kb.mark_keyboard(rows, "Мимо")
    assert [b["text"] for b in out[0]] == ["Иду", "Может быть", "● Мимо"] and out[1][0]["url"] == "https://x"
    assert [b["text"] for b in kb.mark_keyboard(out, None)[0]] == ["Иду", "Может быть", "Мимо"]


def test_dispatcher_builds():
    dp = fresh_dispatcher()
    assert {r.name for r in dp.sub_routers} == {"onboarding", "decisions", "commands", "fallback"}


def test_profile_text_t_profile():
    v = {"values": {v: 2 for v in VALUES} | {"Творчество": 5, "Природа": 5, "Покой": 5, "Азарт": 5, "Смысл": 5},
         "interests": {"Джаз": 3, "Вечеринки": 0},
         "params": {"company": "с детьми", "times": ["вечер"], "budget": 2500, "aesthetics": True},
         "learned_text": "чаще выбираешь: музыка"}
    t = texts.profile_text(v)
    assert t.startswith("<b>Твой профиль</b>\n\n<b>Главные ценности</b>\n")
    assert "Творчество" in t and "В первую очередь: Джаз" in t and "Не показываю: Вечеринки" in t
    assert "Время: вечер\nБюджет: до 2 500 ₽\nЭстетика: важна\nС детьми: да" in t and t.endswith("чаще выбираешь: музыка")
    v["learned_text"] = "пока мало решений — отметь несколько событий"
    assert texts.profile_text(v).endswith(texts.LEARNED_EMPTY)


@pytest.mark.parametrize("selected,tail", [([], "Выбрано 0 из 5"), (["Творчество", "Покой"], "Выбрано 2 из 5: Творчество, Покой"),
                                           (VALUES[:5], "Выбрано 5 из 5: Творчество, Наставничество, Забота, Дружба, Развитие. Нажми «Дальше».")])
def test_values_text(selected, tail):
    assert texts.values_text(selected).endswith(tail) and texts.values_text(selected).startswith("<b>Шаг 1 из 2 · Что для тебя важно</b>")


def test_interests_texts():
    t = texts.interests_text(13)
    assert "Остальные 13 направлений показываю реже" in t and t.startswith("<b>Шаг 2 из 2 · Интересы</b>")
    assert "Остальные 1 направление показываю" in texts.interests_text(1) and "Остальные 3 направления показываю" in texts.interests_text(3)
    assert texts.interests_text(13, changed=True).startswith("Ценности изменились, поэтому я заново подобрал направления.")
    levels = {c: 1 for c in ALL_CATS} | {"Театр": 3, "Кино": 0}
    a = texts.all_text(levels)
    assert "В первую очередь: Театр\nИнтересно: ничего\nИногда: " in a and "Не показываю: Кино" in a
    assert "Главные ценности: Творчество, Покой." in texts.saved_text(["Творчество", "Покой"], levels) and \
        "В первую очередь: Театр." in texts.saved_text(["Творчество", "Покой"], levels)


def test_interests_from_values_formula_unchanged():
    top = {v: 5 for v in VALUES}
    assert all(x == 3 for x in interests_from_values(top).values())
    assert all(x == 1 for x in interests_from_values({v: 0 for v in VALUES}).values())
