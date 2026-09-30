import pytest

from bot.services.mapping import session_types, type_label

BASE = {"pain": "no_initiative", "strategy_state": "team_knows", "decisions": "regular_top_meetings",
        "outcome_6m": "faster_change"}


@pytest.mark.parametrize("override,expected", [
    ({}, ("productivity", None)),
    ({"pain": "strategy_on_paper"}, ("goal", None)),
    ({"strategy_state": "in_my_head"}, ("goal", "productivity")),
    ({"strategy_state": "none", "pain": "partners_disagree"}, ("goal", "sync")),
    ({"pain": "partners_disagree"}, ("sync", None)),
    ({"decisions": "chaotic", "pain": "projects_not_done"}, ("sync", "productivity")),
    ({"pain": "revenue_no_profit"}, ("revenue", None)),
    ({"outcome_6m": "profit_growth"}, ("revenue", "productivity")),
    ({"pain": "scale_unknown"}, ("transformation", None)),
    ({"outcome_6m": "tech_ai", "decisions": "partners_2_3"}, ("sync", "transformation")),
    ({"pain": "revenue_no_profit", "outcome_6m": "tech_ai", "strategy_state": "none"}, ("goal", "revenue")),
])
def test_mapping(content, override, expected):
    assert session_types({**BASE, **override}, content.mapping) == expected


def test_labels(content):
    assert type_label("sync", content.mapping) == "синхронизация команды"
    assert type_label(None, content.mapping) == "—"
