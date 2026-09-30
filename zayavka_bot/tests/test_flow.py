from bot.services import flow
from bot.services.deeplink import parse


def test_linear_order(content):
    n = flow.next_step(content, "pain", "no_initiative")
    assert n.question == "outcome_6m" and not n.finished
    assert flow.next_step(content, "timeline", "month").finished


def test_consultant_branch(content):
    assert flow.next_step(content, "role", "consultant").question == "specialist_need"
    assert flow.next_step(content, "role", "other").question == "pain"  # other идёт по всем 11
    assert flow.next_step(content, "specialist_need", "docs").specialist
    assert flow.prev_question(content, "specialist_need", {}) == "role"
    assert flow.question_number(content, "specialist_need") == 2


def test_back(content):
    assert flow.prev_question(content, "role", {}) is None
    assert flow.prev_question(content, "pain", {}) == "role"
    assert flow.prev_question(content, "timeline", {}) == "revenue"
    assert flow.question_number(content, "timeline") == 11


def test_deeplink():
    assert parse(None) == ("direct", None)
    assert parse("ig") == ("ig", None)
    assert parse("ig_reels1") == ("ig", "reels1")
    assert parse("lecture-spb") == ("lecture", "spb")
    assert parse("ref_ivan") == ("ref", "ivan")
    assert parse("unknown") == ("other", "unknown")
