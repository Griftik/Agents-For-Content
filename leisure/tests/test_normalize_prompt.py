"""Сборка промпта нормализатора: структурные поля RawEvent идут отдельными строками, пустые не выводятся."""
from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from leisure.normalize.llm import build_prompt, raw_extra_lines
from leisure.normalize.schema import RawEvent

BASE = dict(source="kudago", url="https://kudago.com/msk/event/x/", title="Лекция", venue="Музей", price_text="300 рублей",
            date_text="2026-10-24 19:00", text="Текст лекции.")
LABELS = ("Название места в источнике:", "Адрес:", "Метро:", "Координаты:", "Возрастное ограничение:", "Категории источника:")


def prompt(**extra) -> str:
    return build_prompt(RawEvent(**BASE, **extra), "2026-10-23", "2026-10-25")


def card_block(p: str) -> list[str]:
    """Строки раздела «Сырая карточка»."""
    return p.split("## Сырая карточка\n", 1)[1].splitlines()


def test_full_set_of_fields_each_on_its_own_line():
    p = prompt(place_name="Лекторий, малый зал", address="ул. Делегатская, 3", metro="Цветной бульвар", lat=55.7794, lon=37.6084,
               age_restriction="16+", categories=["education", "lecture"])
    lines = card_block(p)
    assert lines == [
        "", "Источник: kudago", "URL: https://kudago.com/msk/event/x/", "Заголовок: Лекция",
        "Дата как в источнике: 2026-10-24 19:00", "Площадка: Музей", "Цена: 300 рублей",
        "Название места в источнике: Лекторий, малый зал", "Адрес: ул. Делегатская, 3", "Метро: Цветной бульвар",
        "Координаты: 55.7794, 37.6084", "Возрастное ограничение: 16+", "Категории источника: education, lecture",
        "Текст:", "Текст лекции.",
    ]
    assert not re.search(r"\{\{\w+\}\}", p)  # все шаблонные поля подставлены (в JSON-схеме «}}» бывает сам по себе)


def test_empty_set_leaves_no_traces():
    p = prompt()
    assert not any(label in p for label in LABELS)
    assert card_block(p)[-3:] == ["Цена: 300 рублей", "Текст:", "Текст лекции."]  # без пустых строк-прокладок
    assert raw_extra_lines(RawEvent(**BASE)) == ""
    assert not re.search(r"\{\{\w+\}\}", p)


def test_partial_set_prints_only_filled_fields():
    p = prompt(address="  ул. Делегатская, 3  ", categories=["", "exhibition"], lat=55.7)  # lat без lon — не координаты
    block = "\n".join(card_block(p))
    assert "Адрес: ул. Делегатская, 3\n" in block and "Категории источника: exhibition\n" in block
    for label in ("Метро:", "Координаты:", "Возрастное ограничение:", "Название места в источнике:"):
        assert label not in block


def test_place_name_equal_to_venue_is_not_repeated():
    assert not any(l.startswith("Название места в источнике") for l in card_block(prompt(place_name="Музей")))
    assert "Название места в источнике: Музей-усадьба" in card_block(prompt(place_name="Музей-усадьба"))


def test_card_text_is_not_treated_as_template():
    p = build_prompt(RawEvent(**{**BASE, "title": "{{venue}} и {{text}}", "text": "{{price_text}}"}), "2026-10-23", "2026-10-25")
    assert "Заголовок: {{venue}} и {{text}}" in p and "\n{{price_text}}" in p


def test_new_fields_are_optional_and_validated():
    raw = RawEvent(source="afisha", url="https://x.example/", title="Событие")
    assert (raw.address, raw.metro, raw.place_name, raw.age_restriction) == ("", "", "", "")
    assert (raw.lat, raw.lon, raw.categories) == (None, None, [])
    raw.categories.append("a")
    assert RawEvent(source="s", url="u", title="t").categories == []  # список не общий между экземплярами
    with pytest.raises(ValidationError):
        RawEvent(source="s", url="u", title="t", lat=91, lon=0)
