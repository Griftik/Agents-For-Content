import shutil

import pytest

from bot.content import ContentError, load_content
from tests.conftest import ROOT


def test_real_content_is_valid(content):
    assert len(content.questions) == 11
    assert content.order[0] == "role" and content.order[-1] == "timeline"
    # коды с подчёркиванием не превращаются в числа (YAML 1.1: 15_50 → 1550)
    assert [c for c, _ in content.question("team_size").options] == ["lt15", "15_50", "50_150", "150_500", "500_plus"]
    assert content.scoring["points"]["team_size"]["15_50"] == 1
    assert content.question("revenue").skippable
    assert content.question("role").branch == {"consultant": "specialist_need"}


def test_texts_format(content):
    assert content.t("progress", n=3) == "Вопрос 3 из 11"
    assert "{pain_text}" not in content.t("hot_offer", pain_text="x")
    # незаполненная переменная не роняет форматирование
    assert "{privacy_url}" in content.t("consent_line")


def test_broken_code_is_rejected(tmp_path):
    d = tmp_path / "content"
    shutil.copytree(ROOT / "content", d)
    p = d / "scoring.yaml"
    p.write_text(p.read_text(encoding="utf-8").replace("owner: 3", "ownr: 3"), encoding="utf-8")
    with pytest.raises(ContentError, match="ownr"):
        load_content(d)


def test_broken_insight_is_rejected(tmp_path):
    d = tmp_path / "content"
    shutil.copytree(ROOT / "content", d)
    p = d / "insights.yaml"
    p.write_text(p.read_text(encoding="utf-8").replace("tried: diy_session", "tried: diy"), encoding="utf-8")
    with pytest.raises(ContentError, match="diy"):
        load_content(d)
