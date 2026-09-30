import logging

from bot.logging_setup import MaskPhonesFilter
from bot.services.cards import SHEET_COLUMNS, admin_card, mask_phone, pain_text, sheet_row

ANS = {"role": "owner", "pain": "projects_not_done", "outcome_6m": "team_drives",
       "strategy_state": "in_my_head", "decisions": "alone", "tried": "diy_session",
       "participants": "top_5_10", "industry": "manufacturing", "team_size": "50_150",
       "revenue": "skip", "timeline": "quarter"}


def test_mask_phone():
    assert mask_phone("+79161234567") == "+7***4567"
    assert mask_phone(None) == "—"


def test_log_filter_masks_phone():
    rec = logging.LogRecord("x", logging.INFO, "", 0, "phone %s", ("+7 916 123-45-67",), None)
    MaskPhonesFilter().filter(rec)
    assert "123" not in rec.getMessage() and "4567" in rec.getMessage()


def test_admin_card_hot(content):
    text = admin_card(content, user_id=42, name="Иван", username="ivan", source="ig", answers=ANS,
                      segment="hot", score=9, session_type="goal", session_type_2="productivity",
                      phone="+79161234567", company="Ромашка")
    assert text.startswith("🔥 Горячий лид (score 9) | источник: ig")
    assert "Иван, Ромашка, роль: Собственник" in text
    assert "выручка не указана" in text
    assert "Боль: Проекты со стратсессий не реализуются" in text
    assert "Тип сессии: определение цели (+ рост производительности)" in text
    assert "Сфера: Производство" in text and "/send 42" in text


def test_admin_card_specialist_one_line(content):
    text = admin_card(content, user_id=7, name="Ольга", username=None, source="tg",
                      answers={"role": "consultant", "specialist_need": "docs"}, segment="specialist",
                      score=0, session_type=None, session_type_2=None, phone=None, company=None)
    assert "\n" not in text and "Специалист" in text and "Документы по подготовке сессии" in text


def test_pain_text(content):
    assert pain_text(content, ANS) == "проекты со стратсессий не реализуются"


def test_sheet_row(content):
    row = sheet_row(content, {"user_id": 42, "answers": ANS, "segment": "hot", "score": 9})
    assert len(row) == len(SHEET_COLUMNS)
    d = dict(zip(SHEET_COLUMNS, row))
    assert d["team_size"] == "50–150" and d["segment"] == "hot" and d["user_id"] == "42"
    assert d["revenue"] == ""  # «Пропустить» в таблицу не пишем
