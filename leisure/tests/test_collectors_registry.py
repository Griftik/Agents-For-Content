"""Реестр источников seed/sources.json: структура, согласованность с каталогом категорий и с реестром коллекторов."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from leisure.collectors import load_collectors
from leisure.collectors.base import REGISTRY
from leisure.core.catalog import ALL_CATS, VALUES

SOURCES_PATH = Path(__file__).parents[1] / "seed" / "sources.json"
DATA = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
SOURCES = DATA["sources"]
TYPES = {"aggregator", "venue", "edu", "ngo", "club", "media", "tg"}
ACCESS = {"api", "rss", "ics", "json", "html", "tg", "manual"}
ROBOTS_SECTIONS = {"открыт", "закрыт", "неизвестно", "не прочитан"}
OLD_SITE_NAMES = {
    "Афиша", "Яндекс Афиша", "KudaGo Москва", "Timepad", "Афиша mos.ru",
    "ГЭС-2 · Гараж · ММОМА · МАММ · Зотов", "Клуб Бутмана · Эссе · Клуб Козлова", "Сколково · РАНХиГС · ВШЭ",
}


def by_id() -> dict[str, dict]:
    return {s["id"]: s for s in SOURCES}


def test_registry_is_big_enough_and_ids_are_unique():
    assert DATA["version"] == 2 and DATA["city"] == "Москва" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", DATA["checked"])
    assert len(SOURCES) >= 60
    ids = [s["id"] for s in SOURCES]
    assert len(ids) == len(set(ids))
    assert len({s["url"] for s in SOURCES if s["type"] != "tg"}) == len([s for s in SOURCES if s["type"] != "tg"])


def test_every_type_is_present():
    got = {s["type"] for s in SOURCES}
    assert got == TYPES


@pytest.mark.parametrize("s", SOURCES, ids=lambda s: s["id"])
def test_each_record_is_complete_and_valid(s):
    assert s["type"] in TYPES and s["access"] in ACCESS
    assert s["name"].strip() and s["url"].startswith("https://")
    assert s["categories"] and set(s["categories"]) <= set(ALL_CATS)
    assert s["needs_key"] and s["legal"].strip()
    reach = s["reachable"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", reach["checked"]) and isinstance(reach["ok"], bool)
    assert isinstance(reach["status"], int)             # в реестре только то, что вообще ответило; молчащее — в not_included
    assert reach["ok"] == (200 <= reach["status"] < 300) or s["id"] in {"kinomax", "vk_events"}   # капча и вход: 200, но не пускают
    assert s["robots"]["section"] in ROBOTS_SECTIONS
    assert isinstance(s["free_now"], bool) and isinstance(s["rank"], int)
    if s["free_now"]:
        assert reach["ok"] and s["needs_key"].startswith("нет") and s["robots"]["section"] != "закрыт"
    if s["type"] == "tg":
        assert s["access"] == "tg" and s["username"] and s["url"] == f"https://t.me/{s['username']}"
        assert s["tg"]["preview_public"] in (True, False) and "active" in s["tg"] and s["tg"]["last_post"]


def test_ranks_are_a_sorted_sequence_and_working_collectors_come_first():
    assert [s["rank"] for s in SOURCES] == list(range(1, len(SOURCES) + 1))
    top = [s["id"] for s in SOURCES[:3]]
    assert set(top) == {"afisha", "club16tons", "bilet_mos"}
    assert all(s["collector"] for s in SOURCES[:3])


def test_sources_with_a_collector_name_a_registered_one():
    load_collectors()
    for s in SOURCES:
        if s["collector"]:
            assert s["collector"] in REGISTRY, f"{s['id']}: коллектор «{s['collector']}» не зарегистрирован"
    # все новые коллекторы есть в реестре и у них есть что собирать
    assert {"afisha", "mosbilet", "club16tons", "telegram"} <= set(REGISTRY)
    used = {s["collector"] for s in SOURCES if s["collector"]}
    assert {"afisha", "mosbilet", "club16tons", "telegram", "kudago", "timepad"} <= used


def test_blocked_sources_are_marked_not_free():
    got = by_id()
    assert not got["kudago"]["free_now"] and got["kudago"]["reachable"]["status"] == 403
    assert not got["timepad"]["free_now"] and got["timepad"]["needs_key"] == "токен"
    assert not got["yafisha"]["free_now"]
    assert got["meetup"]["robots"]["section"] == "закрыт" and not got["meetup"]["free_now"]
    assert not got["vk_events"]["free_now"] and got["vk_events"]["needs_key"] == "вход"
    assert got["afisha"]["free_now"] and got["bilet_mos"]["free_now"] and got["club16tons"]["free_now"]


def test_all_product_categories_have_at_least_one_source():
    covered = {c for s in SOURCES for c in s["categories"]}
    missing = set(ALL_CATS) - covered
    # «Закрытые клубы» по определению не публикуют афишу открыто: источника нет, это вопрос к владельцу (README)
    assert missing <= {"Закрытые клубы"}, f"категории без источников: {missing}"


def test_old_records_are_preserved():
    legacy = {(s.get("legacy") or {}).get("name") or (s.get("legacy") or {}).get("group_name") for s in SOURCES}
    assert OLD_SITE_NAMES <= legacy | {"Афиша mos.ru"}
    got = by_id()
    assert got["bilet_mos"]["legacy"]["name"] == "Афиша mos.ru"        # mos.ru/afisha перенаправляет на bilet.mos.ru
    old_channels = [s for s in SOURCES if s["type"] == "tg" and s.get("useful") is True]
    assert len(old_channels) >= 24
    for s in old_channels:
        assert s["focus"] and s["why"] and s["legacy"]["url"] == s["url"]
    assert "marie" in got and got["marie"]["legacy"]["name"] == "Marie Laveau"


def test_telegram_channels_of_the_old_list_are_all_public_in_the_registry():
    tg = [s for s in SOURCES if s["type"] == "tg"]
    old = [s for s in tg if s.get("legacy")]
    assert len(old) == 25 and all(s["tg"]["preview_public"] for s in old)
    assert len(tg) >= 40 and sum(1 for s in tg if s["tg"]["active"]) >= 35


def test_not_included_list_explains_itself():
    assert DATA["not_included"]
    ids = {s["id"] for s in SOURCES}
    for n in DATA["not_included"]:
        assert n["id"] not in ids and n["reason"].strip() and n["url"].startswith("https://") and n["checked"]


def test_legend_documents_the_vocabulary():
    assert {"type", "access", "needs_key", "robots_section", "free_now", "rank"} <= set(DATA["legend"])


# ─── пакет «Забота» и «Покой» ───

def with_values() -> list[dict]:
    return [s for s in SOURCES if s.get("values")]


def test_values_package_has_at_least_fifteen_records_with_valid_values():
    package = with_values()
    assert len(package) >= 15
    for s in package:
        assert set(s["values"]) <= set(VALUES), f"{s['id']}: неизвестная ценность в {s['values']}"
        assert len(s["values"]) == len(set(s["values"]))


def test_values_package_covers_care_and_calm_with_several_sources_each():
    package = with_values()
    assert sum("Забота" in s["values"] for s in package) >= 8
    assert sum("Покой" in s["values"] for s in package) >= 8
    kinds = {s["type"] for s in package}
    assert {"ngo", "venue", "media", "tg"} <= kinds       # фонды, библиотеки и сад, медиа, каналы


def test_values_package_robots_closed_sources_are_not_free_and_have_no_collector():
    got = by_id()
    for sid in ("dobro", "nekrasovka"):
        assert got[sid]["robots"]["section"] == "закрыт" and not got[sid]["free_now"] and got[sid]["collector"] is None
    assert got["dobro"]["access"] == "json"         # данные есть, но robots.txt: «Disallow: /*?*»


def test_values_package_telegram_channels_are_collected_by_the_telegram_collector():
    got = by_id()
    for sid in ("tg_yogajournal_ru", "tg_nekrasovka_library"):
        assert got[sid]["collector"] == "telegram" and got[sid]["tg"]["active"] and got[sid]["values"]
