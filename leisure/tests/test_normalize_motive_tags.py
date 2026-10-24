"""Теги заботы и покоя (волонтёрство, забота, покой, тишина) на живых фрагментах карточек (fixtures/motive_fragments.json, 2026-10-24).

Две части:
1. Нормализатор: промпт отдаёт модели все четыре тега и правила, когда их ставить (проверка без LLM, по тексту промпта).
2. Доразметка seed/retag.py (read-only): теги заботы, волонтёрства, покоя и тишины на тех же фрагментах (правила kw-volunteer, kw-charity,
   kw-body-calm, kw-walk, kw-quiet и др.).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from leisure.core.catalog import KNOWN_TAGS, VALUE_MAP
from leisure.normalize.llm import build_prompt
from leisure.normalize.schema import RawEvent
from leisure.seed.retag import retag_event

FRAGMENTS = json.loads((Path(__file__).with_name("fixtures") / "motive_fragments.json").read_text(encoding="utf-8"))["cards"]
BY_ID = {c["id"]: c for c in FRAGMENTS}
MOTIVE_TAGS = ("волонтёрство", "забота", "покой", "тишина")


def tags_of(card: dict) -> set[str]:
    ev = {"title": card["title"], "subcategory": "", "description": card["text"], "why_fit_hint": "", "category": "Нетривиальное", "tags": []}
    return set(retag_event(ev)[0]["tags"])


# ─── нормализатор ───

def test_motive_tags_are_known_and_carry_the_expected_values():
    assert set(MOTIVE_TAGS) <= KNOWN_TAGS
    assert ("Забота", 1.0) in VALUE_MAP["забота"] and ("Забота", 1.0) in VALUE_MAP["волонтёрство"]
    assert ("Покой", 1.0) in VALUE_MAP["покой"] and ("Покой", 0.8) in VALUE_MAP["тишина"]


@pytest.mark.parametrize("card", FRAGMENTS, ids=lambda c: c["id"])
def test_prompt_offers_motive_tags_and_explains_when_to_use_them(card):
    raw = RawEvent(source="fixture", url=card["source"], title=card["title"], text=card["text"])
    prompt = build_prompt(raw, "2026-10-24", "2026-10-31")
    tag_line = next(line for line in prompt.splitlines() if line.startswith("- `tags`"))
    assert all(t in tag_line for t in MOTIVE_TAGS)
    guide = next(line for line in prompt.splitlines() if line.startswith("- Мотивы заботы и покоя"))
    assert all(f"`{t}`" in guide for t in MOTIVE_TAGS)
    assert "«Тишина» как название композиции" in guide                # слово из названия песни тегом не считается
    assert card["title"] in prompt and card["text"][:40] in prompt    # сама карточка дошла до модели


# ─── retag: что работает сейчас ───

def test_retag_sets_volunteering_on_the_word_volunteer_and_calm_on_retreat():
    assert "волонтёрство" in tags_of(BY_ID["mosvolonter-lead"])         # «волонтерской деятельности»
    assert "покой" in tags_of(BY_ID["yogajournal-retreat"])             # «РЕТРИТ»


# ─── retag: фрагменты, которые раньше не размечались ───

@pytest.mark.parametrize("card_id, tag", [
    ("cleangames-lead", "волонтёрство"),             # «уборки», «субботникам»
    ("yogajournal-mantra-yoga", "покой"),            # «йога» не покрыта
    ("afisha-yoga", "покой"),
    ("gbsad-excursion", "природа"),                  # ботанический сад, лесные тропы
])
def test_retag_should_tag_this_fragment(card_id, tag):
    assert tag in tags_of(BY_ID[card_id])


@pytest.mark.parametrize("card_id", ["takiedela-charity-musical", "cleangames-lead"])
def test_retag_should_set_care_tag_on_charity_and_cleanup(card_id):
    assert "забота" in tags_of(BY_ID[card_id])


@pytest.mark.parametrize("card_id", ["mosbilet-song-title-silence", "16tons-band-break"])
def test_retag_should_not_tag_silence_from_a_song_title_or_a_band_break(card_id):
    assert "тишина" not in tags_of(BY_ID[card_id])


def test_each_fragment_gets_exactly_what_it_wants():
    """Все 9 карточек: нужные теги стоят, лишних (want_not) нет."""
    for card in FRAGMENTS:
        tags = tags_of(card)
        assert set(card.get("want", [])) <= tags, card["id"]
        assert not set(card.get("want_not", [])) & tags, card["id"]
    assert "забота" in tags_of(BY_ID["takiedela-charity-musical"]) and "тишина" not in tags_of(BY_ID["mosbilet-song-title-silence"])
