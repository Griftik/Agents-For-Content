"""Доразметка seed (seed/retag.py) и расширение ценностей до 19 (docs/VALUES-AUDIT.md)."""
import json
import re

import pytest

from leisure.core.catalog import KNOWN_TAGS, VALUE_MAP, VALUES
from leisure.seed import retag
from leisure.seed.retag import coverage, retag_event

from .conftest import ROOT


def _ev(**over):
    base = {"slug": "x", "title": "Событие", "category": "Джаз", "subcategory": "", "description": "", "why_fit_hint": "",
            "tags": ["музыка"], "audience_kids": False}
    return {**base, **over}


def _tags(**over):
    return retag_event(_ev(**over))[0]["tags"]


def test_seed_is_in_sync_with_rules_and_idempotent(seed_raw):
    again, info = retag.retag(seed_raw)
    assert again == seed_raw and not info["added"] and info["tagged"] == 0
    assert retag.main(["--check"]) == 0


def test_every_value_covered_except_documented_gap(seed_raw):
    cov = coverage(seed_raw)
    assert set(cov) == set(VALUES) and len(VALUES) == 19
    assert [v for v, n in cov.items() if n == 0] == ["Забота"]            # в seed нет заботы и волонтёрства — см. RETAG.md
    report = (ROOT / "seed" / "RETAG.md").read_text(encoding="utf-8")
    assert "Ценности без единого события: Забота." in report
    assert sum(cov.values()) / len(seed_raw) > 3.0                           # было 2.80 ценности на событие


def test_all_tags_known_and_nothing_removed(seed_raw):
    assert all(t in KNOWN_TAGS for e in seed_raw for t in e["tags"])
    assert all(t in KNOWN_TAGS for r in retag.RULES for t in r.tags)


@pytest.mark.parametrize("over,expected", [
    ({"category": "Винные бары"}, ["вкус"]),
    ({"category": "Вечеринки"}, ["веселье"]),
    ({"category": "Волейбол: матчи"}, ["болеть", "азарт"]),
    ({"category": "Волейбол"}, ["соревнование"]),
    ({"title": "Русская баня и тишина"}, ["покой", "тишина"]),
    ({"description": "Вечер вдвоём, романтичный"}, ["романтика"]),
    ({"title": "Стендап и квиз"}, ["веселье", "игра"]),
    ({"description": "Лекция о философии"}, ["смысл"]),
    ({"description": "Волонтёрский день"}, ["волонтёрство"]),
    ({"description": "Диско 90-х, ретро"}, ["ностальгия"]),
    ({"description": "Ритуалы и обряды"}, ["ритуал"]),
])
def test_rules_add_expected_tags(over, expected):
    assert _tags(**over) == ["музыка"] + expected


def test_rules_avoid_known_false_hits():
    assert _tags(description="ретроспектива художника") == ["музыка"]            # «ретро» не в «ретроспектива»
    assert _tags(description="инквизиция, реквизит") == ["музыка"]               # «квиз» только как слово
    assert _tags(description="«громкая тишина касания»") == ["музыка"]
    assert _tags(description="не в студии для свиданий") == ["музыка"]
    assert _tags(description="шнобелевские премии") == ["музыка"]
    assert _tags(description="старообрядческая молельня") == ["музыка"]


def test_kids_rule_needs_audience_kids_flag_and_family_formats_do_not():
    assert _tags(description="детская программа") == ["музыка"]
    assert _tags(description="детская программа", audience_kids=True) == ["музыка", "дети"]
    assert _tags(description="сеанс: семейный — в 13:00") == ["музыка", "семья"]
    assert _tags(description="лучше смотреть без детей") == ["музыка"]


def test_new_tags_map_to_new_values():
    audit = {"веселье": ("Веселье", 1.0), "вкус": ("Удовольствие", 1.0), "азарт": ("Азарт", 1.0), "покой": ("Покой", 1.0),
             "романтика": ("Близость", 1.0), "смысл": ("Смысл", 1.0), "духовно": ("Смысл", 1.0)}
    for tag, pair in audit.items():
        assert pair in VALUE_MAP[tag]
    assert dict(VALUE_MAP["болеть"]) == {"Азарт": 0.8, "Единство/Дружба": 0.5}
    assert dict(VALUE_MAP["ностальгия"]) == {"Сохранение традиций": 0.7, "Веселье": 0.3}
    assert len(VALUE_MAP) == 39


def test_prototype_parity_fixture_untouched():
    """Фикстуры прототипа не содержат новых тегов — паритет не зависит от доразметки."""
    fx = json.loads((ROOT / "tests" / "fixtures" / "prototype_events.json").read_text(encoding="utf-8"))
    new = set(re.findall(r"[а-яё]+", "веселье игра юмор вкус комфорт азарт болеть соревнование покой тишина романтика смысл духовно "
                                   "приключение статус волонтёрство ностальгия"))
    assert not {t for e in fx for t in e["tags"]} & new
