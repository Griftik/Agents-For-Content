"""Скоринг и сегментация — таблица случаев (раздел 4, не меньше 12 строк)."""
import pytest

from bot.services.scoring import score, segment


def A(role, team, timeline, participants="top_5_10", revenue="skip", **kw):
    return {"role": role, "team_size": team, "timeline": timeline,
            "participants": participants, "revenue": revenue, **kw}


CASES = [
    # (ответы, ожидаемый сегмент, баллы)
    (A("owner", "50_150", "quarter"), "hot", 3 + 2 + 2 + 2),                          # 9
    (A("ceo", "150_500", "month", "extended_10_30", "gt2b"), "hot", 3 + 3 + 3 + 2 + 2),  # 13 = максимум
    (A("top", "15_50", "month", "me_partners", "lt100m"), "hot", 2 + 1 + 3 + 1),      # 7 = ровно порог
    (A("top", "15_50", "quarter", "me_partners"), "warm", 2 + 1 + 2 + 1),             # 6 < порога
    (A("owner", "lt15", "month", "top_5_10", "gt2b"), "warm", 3 + 0 + 3 + 2 + 2),     # 10, но до 15 человек
    (A("owner", "500_plus", "year", "extended_10_30", "gt2b"), "warm", 3 + 3 + 1 + 2 + 2),  # срок «год»
    (A("ceo", "150_500", "exploring"), "warm", 3 + 3 + 0 + 2),                        # «изучаю»
    (A("hr_dev", "50_150", "quarter"), "warm_initiator", 1 + 2 + 2 + 2),
    (A("other", "500_plus", "month"), "warm_initiator", 1 + 3 + 3 + 2),               # other = hr_dev
    (A("hr_dev", "15_50", "month"), "specialist", 1 + 1 + 3 + 2),                     # маленькая компания
    (A("hr_dev", "150_500", "year"), "specialist", 1 + 3 + 1 + 2),                    # нет срочности
    (A("other", "lt15", "exploring", "unknown"), "specialist", 1),
    (A("consultant", "500_plus", "month", "extended_10_30", "gt2b"), "specialist", 0 + 3 + 3 + 2 + 2),
    ({"role": "consultant", "specialist_need": "docs"}, "specialist", 0),            # ветка консультанта
    (A("owner", "15_50", "quarter", "unknown", "100_500m"), "hot", 3 + 1 + 2 + 0 + 1),  # выручка добирает до 7
]


@pytest.mark.parametrize("answers,expected,points", CASES)
def test_segment_table(content, answers, expected, points):
    assert score(answers, content.scoring) == points
    assert segment(answers, content.scoring) == (expected, points)


def test_budget_not_in_scoring(content):
    assert "budget" not in content.scoring["points"]


def test_threshold_is_editable(content):
    s = dict(content.scoring, hot_threshold=10)
    assert segment(A("owner", "50_150", "quarter"), s)[0] == "warm"  # 9 < 10
