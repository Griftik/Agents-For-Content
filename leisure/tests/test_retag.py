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
    ({"title": "Русская баня"}, ["покой"]),                  # голое слово «тишина» тег не ставит (название песни, пауза группы)
    ({"description": "Вечер вдвоём, романтичный"}, ["романтика"]),
    ({"title": "Стендап и квиз"}, ["веселье", "игра"]),
    ({"description": "Лекция о философии"}, ["смысл"]),
    ({"description": "Волонтёрский день"}, ["волонтёрство", "забота"]),
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


@pytest.mark.parametrize("over,expected", [
    ({"description": "Мюзикл в поддержку фонда «Не напрасно»"}, ["забота"]),
    ({"description": "Помогите проводить уборки, не скучные субботники"}, ["волонтёрство", "забота"]),
    ({"description": "Добровольцы собирают вещи"}, ["волонтёрство", "забота"]),
    ({"description": "Благотворительный вечер, сбор средств"}, ["забота"]),
    ({"description": "Помощь животным из приюта"}, ["забота"]),
    ({"title": "Йога среди искусства"}, ["покой", "тело"]),
    ({"description": "Хаммам и банный день"}, ["покой"]),
    ({"description": "Читальный зал и чтения вслух"}, ["тишина"]),
    ({"description": "Лесные тропы и ботанический сад"}, ["покой", "природа"]),
    ({"description": "Неспешная прогулка по ботаническому саду"}, ["тишина", "покой", "природа"]),   # «неспешн» ловит ещё kw-quiet2
    ({"description": "Тихий вечер в зале, музыка в тишине"}, ["тишина"]),
])
def test_motive_rules_care_and_calm(over, expected):
    assert _tags(**over) == ["музыка"] + expected


def test_quiet_rule_ignores_song_title_and_band_break():
    assert _tags(description="композиции «Тишина», «Березы»") == ["музыка"]
    assert _tags(description="потом будет тишина, студия и новые песни") == ["музыка"]
    assert _tags(description="громкая тишина касания") == ["музыка"]


def test_report_has_no_stale_proposals_and_states_care_and_calm_coverage():
    report = (ROOT / "seed" / "RETAG.md").read_text(encoding="utf-8")
    assert "Предложения по правилам" not in report and "## Забота и Покой после правил" in report
    cov = coverage(json.loads((ROOT / "seed" / "events_2026-10-23.json").read_text(encoding="utf-8")))
    assert f"«Забота» {cov['Забота']} (было 0), «Покой» {cov['Покой']} (было 0)" in report


def test_baseline_strips_rule_tags_but_keeps_prototype_ones(seed_raw):
    base = retag.baseline(seed_raw)
    assert retag.retag(base)[0] == seed_raw                              # правила восстанавливают файл из исходной разметки
    assert sum(len(e["tags"]) for e in base) < sum(len(e["tags"]) for e in seed_raw)
    assert all(("тело" in e["tags"]) == ("тело" in b["tags"]) for e, b in zip(seed_raw, base))
