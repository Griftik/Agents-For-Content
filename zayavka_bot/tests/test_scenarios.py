"""Сквозные сценарии — критерии приёмки MVP (раздел 15, п. 1–5)."""
from __future__ import annotations

import shutil
from datetime import timedelta

import pytest
from aiogram import Bot
from sqlalchemy import update

from bot.content import get_content
from bot.db import repo
from bot.db.models import ScheduledJob, utcnow
from bot.db.session import session
from bot.handlers import admin as admin_h
from bot.main import build_dispatcher
from bot.services import scheduler
from tests.conftest import ADMIN, ROOT
from tests.fakebot import FakeTelegram, RecordingSession

HOT = {"role": "owner", "pain": "projects_not_done", "outcome_6m": "team_drives",
       "strategy_state": "in_my_head", "decisions": "alone", "tried": "diy_session",
       "participants": "top_5_10", "industry": "manufacturing", "team_size": "50_150",
       "revenue": "skip", "timeline": "quarter"}
WARM = {**HOT, "timeline": "year"}


_DP = None


def _dp():
    # роутеры — синглтоны модулей, к диспетчеру подключаются один раз
    global _DP
    if _DP is None:
        _DP = build_dispatcher()
    return _DP


@pytest.fixture
async def tg(db):
    admin_h.pending_send.clear()
    session = RecordingSession()
    bot = Bot("123456:TEST", session=session)
    yield FakeTelegram(_dp(), bot, session)


async def fill(tg: FakeTelegram, uid: int, answers: dict[str, str]) -> None:
    u = await repo.get_user(uid)
    if u is None or u.consent_at is None:
        await tg.press(uid, "consent:toggle")
    await tg.press(uid, "app:start")
    for q in get_content().order:
        await tg.press(uid, f"a:{q}:{answers[q]}")


async def test_hot_lead_full_path(tg):
    uid = 501
    await tg.text(uid, "/start ig_reels")
    u = await repo.get_user(uid)
    assert (u.source, u.ref) == ("ig", "reels")
    assert get_content().t("welcome") in tg.texts(uid)

    await fill(tg, uid, HOT)
    texts = "\n".join(tg.texts(uid))
    assert "Два наблюдения" in texts and "Проекты не доходят до реализации" in texts
    assert "Нажимая кнопку" not in texts  # согласие уже дано галочкой, без строки с URL
    assert (await repo.get_user(uid)).stage == "contact"

    await tg.contact(uid, "+7 916 123-45-67")
    lead = await repo.get_lead(uid)
    assert lead.phone == "+79161234567" and lead.consent_at is not None
    await tg.text(uid, "Ромашка")

    lead = await repo.get_lead(uid)
    assert (lead.segment, lead.score, lead.company) == ("hot", 9, "Ромашка")
    assert (lead.session_type, lead.session_type_2) == ("goal", "productivity")

    # админу — карточка с верным сегментом
    card = next(t for t in tg.texts(ADMIN) if "Горячий лид" in t)
    assert "score 9" in card and "источник: ig:reels" in card and "+79161234567" in card

    # горячему — hot_offer с кнопкой записи ДО документа, потом report_pending
    user_texts = tg.texts(uid)
    i_offer = next(i for i, t in enumerate(user_texts) if t.startswith("Посмотрел ваши ответы"))
    i_pending = next(i for i, t in enumerate(user_texts) if t.startswith("Принял."))
    assert i_offer < i_pending
    assert "проекты со стратсессий не реализуются" in user_texts[i_offer]

    await tg.press(uid, "book")
    kb = [m for m in tg.sent(uid) if m.text == get_content().t("hot_booking_url_text")][-1].reply_markup
    assert kb.inline_keyboard[0][0].url == "https://example.com/book"
    assert any("открыл ссылку записи" in t for t in tg.texts(ADMIN))

    # админ отправляет документ через /send, пользователь получает его с «Что дальше»
    tg.clear()
    await tg.text(ADMIN, f"/send {uid}")
    await tg.document(ADMIN)
    assert get_content().t("report_sent_intro") in tg.texts(uid)
    copy = tg.sent(uid, "CopyMessage")[0]
    assert copy.reply_markup.inline_keyboard[0][0].callback_data == "next"
    assert (await repo.get_lead(uid)).status == "report_sent"


async def test_consultant_gets_docs_after_two_questions(tg, tmp_path, monkeypatch):
    from bot.config import get_settings

    d = tmp_path / "content"
    shutil.copytree(ROOT / "content", d)
    (d / "docs" / "docs").mkdir()
    (d / "docs" / "docs" / "checklist.pdf").write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(get_settings(), "content_dir", d)

    uid = 502
    await tg.text(uid, "/start tg")
    await tg.press(uid, "consent:toggle")
    await tg.press(uid, "app:start")
    await tg.press(uid, "a:role:consultant")
    assert (await repo.get_user(uid)).stage == "q:specialist_need"
    await tg.press(uid, "a:specialist_need:docs")

    assert len(tg.sent(uid, "SendDocument")) == 1
    lead = await repo.get_lead(uid)
    assert lead.segment == "specialist"
    assert not any(t.startswith("Посмотрел ваши ответы") for t in tg.texts(uid))  # не в продажах
    assert not any("Два наблюдения" in t for t in tg.texts(uid))  # остальные вопросы не задавались
    await tg.press(uid, "train:yes")
    assert (await repo.get_answers(uid))["training_announce"] == "yes"


async def test_back_and_skip(tg):
    uid = 503
    await tg.text(uid, "/start")
    await tg.press(uid, "consent:toggle")
    await tg.press(uid, "app:start")
    await tg.press(uid, "a:role:owner")
    await tg.press(uid, "a:pain:no_time_ops")
    await tg.press(uid, "back:outcome_6m")
    assert (await repo.get_user(uid)).stage == "q:pain"
    await tg.press(uid, "a:pain:scale_unknown")  # перезапись ответа
    assert (await repo.get_answers(uid))["pain"] == "scale_unknown"
    # старая кнопка с другого вопроса игнорируется
    await tg.press(uid, "a:role:ceo")
    assert (await repo.get_answers(uid))["role"] == "owner"
    # рестарт посреди заявки → предложение продолжить с того же вопроса
    tg.clear()
    await tg.text(uid, "/start")
    assert tg.texts(uid)[-1] == get_content().t("resume", n=3)


async def test_no_phone_timeout_and_later_contact(tg):
    uid = 504
    await tg.text(uid, "/start site")
    await fill(tg, uid, WARM)
    # 10 минут без телефона → задание созревает
    async with session() as s:
        await s.execute(update(ScheduledJob).where(ScheduledJob.kind == "contact_timeout")
                        .values(run_at=utcnow() - timedelta(seconds=1)))
        await s.commit()
    for job in await repo.take_due_jobs():
        await scheduler.handle(tg.bot, job)

    lead = await repo.get_lead(uid)
    assert lead.segment == "warm" and lead.phone is None
    assert get_content().t("report_pending") in tg.texts(uid)

    # разбор приходит без телефона → после него одна кнопка «Поделиться телефоном»
    tg.clear()
    await tg.text(ADMIN, f"/send {uid} Текст разбора")
    assert "Текст разбора" in tg.texts(uid)
    rk = tg.last_markup(uid)
    assert rk.keyboard[0][0].request_contact and len(rk.keyboard) == 1
    await tg.contact(uid, "+79990000000")
    assert (await repo.get_lead(uid)).phone == "+79990000000"
    assert any("оставил телефон после разбора" in t for t in tg.texts(ADMIN))

    # «Что дальше» для тёплого — warm_intro с кнопкой записи
    await tg.press(uid, "next")
    assert get_content().t("warm_intro") in tg.texts(uid)


async def test_foreign_contact_rejected(tg):
    uid = 505
    await tg.text(uid, "/start")
    await fill(tg, uid, HOT)
    await tg.contact(uid, "+70000000000", owner=999)
    assert (await repo.get_lead(uid)) is None or (await repo.get_lead(uid)).phone is None


async def test_contact_later_button_then_skip_company(tg):
    uid = 506
    await tg.text(uid, "/start")
    await fill(tg, uid, WARM)
    await tg.text(uid, get_content().t("contact_later_button"))
    assert (await repo.get_user(uid)).stage == "company"
    await tg.press(uid, "company:skip")
    lead = await repo.get_lead(uid)
    assert lead.segment == "warm" and lead.company is None and lead.phone is None


async def test_text_outside_scenario_forwarded(tg):
    uid = 507
    await tg.text(uid, "/start")
    await tg.text(uid, "Здравствуйте, вопрос")
    assert tg.texts(uid)[-1] == get_content().t("text_forwarded")
    assert tg.sent(ADMIN, "ForwardMessage")


async def test_delete_me(tg):
    uid = 508
    await tg.text(uid, "/start")
    await fill(tg, uid, HOT)
    await tg.contact(uid, "+79161234567")
    await tg.press(uid, "company:skip")
    await tg.text(uid, "/delete_me")
    await tg.press(uid, "del:yes")
    u, lead = await repo.get_user(uid), await repo.get_lead(uid)
    assert u.first_name is None and u.deleted_at is not None
    assert lead.phone is None and lead.status == "deleted"
    assert await repo.get_answers(uid) == {}
    # обезличенная статистика осталась
    assert any(e.name == "segment_assigned" for e in await repo.events_since(u.created_at))


async def test_stats_and_reload(tg, tmp_path, monkeypatch):
    for i, ans in enumerate([HOT, WARM]):
        uid = 600 + i
        await tg.text(uid, "/start ig")
        await fill(tg, uid, ans)
        await tg.contact(uid, f"+7916000000{i}")
        await tg.press(uid, "company:skip")
    # бросил на вопросе 3
    await tg.text(610, "/start tg")
    await tg.press(610, "consent:toggle")
    await tg.press(610, "app:start")
    await tg.press(610, "a:role:owner")
    await tg.press(610, "a:pain:no_time_ops")

    tg.clear()
    await tg.text(ADMIN, "/stats 7")
    out = tg.texts(ADMIN)[-1]
    assert "старты 3 | начали 3 (100%) | завершили 2 (67%) | телефон 2 (67%)" in out
    assert "горячие 1 (50%) от контактов" in out
    assert "— ig" in out and "— tg" in out
    assert "1 — 3. Что должно измениться" in out

    # /reload подхватывает правку YAML без рестарта
    from bot.config import get_settings

    d = tmp_path / "content"
    shutil.copytree(ROOT / "content", d)
    p = d / "texts.yaml"
    p.write_text(p.read_text(encoding="utf-8").replace('text_forwarded: "Передал Евгению, ответит лично."',
                                                        'text_forwarded: "Новый текст."'), encoding="utf-8")
    monkeypatch.setattr(get_settings(), "content_dir", d)
    await tg.text(ADMIN, "/reload")
    assert tg.texts(ADMIN)[-1].startswith("Перечитал")
    await tg.text(777, "привет")
    assert tg.texts(777)[-1] == "Новый текст."

    # битый YAML не принимается, работает прежняя версия
    (d / "scoring.yaml").write_text("points: [", encoding="utf-8")
    await tg.text(ADMIN, "/reload")
    assert "прежняя версия" in tg.texts(ADMIN)[-1]
    assert get_content().t("text_forwarded") == "Новый текст."


async def test_admin_contacted_button(tg):
    uid = 509
    await tg.text(uid, "/start")
    await fill(tg, uid, HOT)
    await tg.contact(uid, "+79161234567")
    await tg.press(uid, "company:skip")
    await tg.press(ADMIN, f"adm:contacted:{uid}")
    lead = await repo.get_lead(uid)
    assert lead.contacted_at is not None and lead.status == "contacted"


async def test_non_admin_cannot_send(tg):
    await tg.text(42, "/send 1 hi")
    assert tg.texts(42)[-1] == get_content().t("text_forwarded")  # ушло как обычное сообщение
