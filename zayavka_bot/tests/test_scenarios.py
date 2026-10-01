"""Сквозные сценарии — критерии приёмки MVP (раздел 15, п. 1–5), заявка — в мини-приложении."""
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
from tests.appclient import MiniApp
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
    rs = RecordingSession()
    bot = Bot("123456:TEST", session=rs)
    ft = FakeTelegram(_dp(), bot, rs)
    async with MiniApp(bot) as app:
        ft.app = app
        yield ft


async def fill(tg: FakeTelegram, uid: int, answers: dict[str, str]) -> dict:
    """Галочка, «Заполнить заявку», 11 ответов — в приложении."""
    s = await tg.app.state(uid)
    if s["screen"] == "welcome" and not s["consent"]:
        await tg.app.act(uid, "consent", value=True)
    s = await tg.app.act(uid, "start")
    for q in get_content().order:
        assert s["screen"] == "question" and s["question"]["code"] == q, s
        s = await tg.app.act(uid, "answer", q=q, a=answers[q])
    return s


async def share_phone(tg: FakeTelegram, uid: int, phone: str) -> dict:
    """WebApp.requestContact: Telegram присылает контакт в чат, приложение проверяет."""
    await tg.contact(uid, phone)
    return await tg.app.act(uid, "contact_check")


async def lead(tg: FakeTelegram, uid: int, answers: dict[str, str], phone: str | None = "+79161234567",
               company: str = "", start: str = "/start") -> dict:
    await tg.text(uid, start)
    await fill(tg, uid, answers)
    if phone:
        await share_phone(tg, uid, phone)
    else:
        await tg.app.act(uid, "contact_skip")
    return await tg.app.act(uid, "company", text=company)


async def test_hot_lead_full_path(tg):
    c = get_content()
    uid = 501
    await tg.text(uid, "/start ig_reels")
    u = await repo.get_user(uid)
    assert (u.source, u.ref) == ("ig", "reels")
    welcome = [m for m in tg.sent(uid) if m.text == c.t("welcome")][-1]
    assert welcome.reply_markup.inline_keyboard[0][0].web_app.url == "https://app.example"

    s = await fill(tg, uid, HOT)
    assert s["screen"] == "contact"
    assert s["teaser_intro"].startswith("Спасибо. Два наблюдения")
    assert s["insights"][0].startswith("Проекты не доходят до реализации")
    assert (await repo.get_user(uid)).stage == "contact"

    s = await share_phone(tg, uid, "+7 916 123-45-67")
    assert s["screen"] == "company"
    ld = await repo.get_lead(uid)
    assert ld.phone == "+79161234567" and ld.consent_at is not None
    s = await tg.app.act(uid, "company", text="Ромашка")
    assert s["screen"] == "home"

    ld = await repo.get_lead(uid)
    assert (ld.segment, ld.score, ld.company) == ("hot", 9, "Ромашка")
    assert (ld.session_type, ld.session_type_2) == ("goal", "productivity")

    card = next(t for t in tg.texts(ADMIN) if "Горячий лид" in t)
    assert "score 9" in card and "источник: ig:reels" in card and "+79161234567" in card

    # горячему — предложение созвониться ДО документа: в приложении и в чате
    assert s["offer"]["text"].startswith("Посмотрел ваши ответы")
    assert "проекты со стратсессий не реализуются" in s["offer"]["text"]
    assert s["status"] == c.t("report_pending")
    texts = tg.texts(uid)
    i_offer = next(i for i, t in enumerate(texts) if t.startswith("Посмотрел ваши ответы"))
    i_pending = next(i for i, t in enumerate(texts) if t.startswith("Принял."))
    assert i_offer < i_pending

    r = await tg.app.act(uid, "book")
    assert r["open_url"] == "https://example.com/book"
    assert any("открыл ссылку записи" in t for t in tg.texts(ADMIN))

    # админ отправляет документ через /send, пользователь получает его с «Что дальше»
    tg.clear()
    await tg.text(ADMIN, f"/send {uid}")
    await tg.document(ADMIN)
    assert c.t("report_sent_intro") in tg.texts(uid)
    copy = tg.sent(uid, "CopyMessage")[0]
    assert copy.reply_markup.inline_keyboard[0][0].callback_data == "next"
    assert (await repo.get_lead(uid)).status == "report_sent"
    assert (await tg.app.state(uid))["status"] == c.t("app_report_in_chat")


async def test_consultant_gets_docs_after_two_questions(tg, tmp_path, monkeypatch):
    from bot.config import get_settings

    d = tmp_path / "content"
    shutil.copytree(ROOT / "content", d)
    (d / "docs" / "docs").mkdir()
    (d / "docs" / "docs" / "checklist.pdf").write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(get_settings(), "content_dir", d)

    uid = 502
    await tg.text(uid, "/start tg")
    await tg.app.act(uid, "consent", value=True)
    await tg.app.act(uid, "start")
    s = await tg.app.act(uid, "answer", q="role", a="consultant")
    assert s["question"]["code"] == "specialist_need" and s["question"]["total"] is None
    s = await tg.app.act(uid, "answer", q="specialist_need", a="docs")
    assert s["screen"] == "specialist"
    assert s["links"]["channel"] == "https://t.me/neurostrategy"

    assert len(tg.sent(uid, "SendDocument")) == 1
    assert (await repo.get_lead(uid)).segment == "specialist"
    assert not any(t.startswith("Посмотрел ваши ответы") for t in tg.texts(uid))  # не в продажах
    s = await tg.app.act(uid, "training", value=True)
    assert s["screen"] == "home"
    assert (await repo.get_answers(uid))["training_announce"] == "yes"
    assert any("хочет анонс обучения" in t for t in tg.texts(ADMIN))


async def test_back_and_stale_answers(tg):
    uid = 503
    await tg.text(uid, "/start")
    await tg.app.act(uid, "consent", value=True)
    await tg.app.act(uid, "start")
    await tg.app.act(uid, "answer", q="role", a="owner")
    await tg.app.act(uid, "answer", q="pain", a="no_time_ops")
    s = await tg.app.act(uid, "back")
    assert s["question"]["code"] == "pain" and s["question"]["selected"] == "no_time_ops"
    await tg.app.act(uid, "answer", q="pain", a="scale_unknown")  # перезапись ответа
    assert (await repo.get_answers(uid))["pain"] == "scale_unknown"
    # двойное нажатие / старый экран не ломает порядок
    s = await tg.app.act(uid, "answer", q="role", a="ceo")
    assert (await repo.get_answers(uid))["role"] == "owner" and s["question"]["code"] == "outcome_6m"
    # закрыл приложение — /start в чате предлагает продолжить, приложение открывается на том же вопросе
    tg.clear()
    await tg.text(uid, "/start")
    assert tg.texts(uid)[-1] == get_content().t("resume", n=3)
    assert (await tg.app.state(uid))["question"]["code"] == "outcome_6m"


async def test_revenue_skip_and_progress(tg):
    uid = 511
    await tg.text(uid, "/start")
    s = await fill(tg, uid, {**WARM})
    assert s["screen"] == "contact"
    await tg.app.act(uid, "contact_skip")
    await tg.app.act(uid, "company", text="")
    s = await tg.app.act(uid, "restart")
    for q in get_content().order[:9]:
        s = await tg.app.act(uid, "answer", q=q, a=WARM[q])
    q = s["question"]
    assert q["code"] == "revenue" and q["progress"] == "Вопрос 10 из 11"
    assert any(o["code"] == "skip" for o in q["options"])


async def test_no_phone_timeout_and_later_contact(tg):
    uid = 504
    await tg.text(uid, "/start site")
    await fill(tg, uid, WARM)
    async with session() as s:
        await s.execute(update(ScheduledJob).where(ScheduledJob.kind == "contact_timeout")
                        .values(run_at=utcnow() - timedelta(seconds=1)))
        await s.commit()
    for job in await repo.take_due_jobs():
        await scheduler.handle(tg.bot, job)

    ld = await repo.get_lead(uid)
    assert ld.segment == "warm" and ld.phone is None
    assert get_content().t("report_pending") in tg.texts(uid)
    assert (await tg.app.state(uid))["screen"] == "home"

    # разбор приходит без телефона → после него одна кнопка «Поделиться телефоном» в чате
    tg.clear()
    await tg.text(ADMIN, f"/send {uid} Текст разбора")
    assert "Текст разбора" in tg.texts(uid)
    rk = tg.last_markup(uid)
    assert rk.keyboard[0][0].request_contact and len(rk.keyboard) == 1
    await tg.contact(uid, "+79990000000")
    assert (await repo.get_lead(uid)).phone == "+79990000000"
    assert any("оставил телефон после разбора" in t for t in tg.texts(ADMIN))

    # «Что дальше» для тёплого — warm_intro с кнопкой записи; в приложении — тоже
    await tg.press(uid, "next")
    assert get_content().t("warm_intro") in tg.texts(uid)
    assert (await tg.app.state(uid))["offer"]["text"] == get_content().t("warm_intro")


async def test_contact_check_without_phone_waits_then_asks_again(tg, monkeypatch):
    from bot.webapp import api

    monkeypatch.setattr(api, "CONTACT_WAIT_SEC", 0.3)
    uid = 512
    await tg.text(uid, "/start")
    await fill(tg, uid, WARM)
    s = await tg.app.act(uid, "contact_check")
    assert s["screen"] == "contact" and s["toast"] == get_content().t("app_contact_wait")


async def test_foreign_contact_rejected(tg):
    uid = 505
    await tg.text(uid, "/start")
    await fill(tg, uid, HOT)
    await tg.contact(uid, "+70000000000", owner=999)
    ld = await repo.get_lead(uid)
    assert ld is None or ld.phone is None
    assert (await repo.get_user(uid)).stage == "contact"


async def test_contact_later_then_skip_company(tg):
    s = await lead(tg, 506, WARM, phone=None)
    assert s["screen"] == "home"
    ld = await repo.get_lead(506)
    assert ld.segment == "warm" and ld.company is None and ld.phone is None


async def test_text_outside_scenario_forwarded(tg):
    uid = 507
    await tg.text(uid, "/start")
    await tg.text(uid, "Здравствуйте, вопрос")
    assert tg.texts(uid)[-1] == get_content().t("text_forwarded")
    assert tg.sent(ADMIN, "ForwardMessage")


async def test_delete_from_app_and_chat(tg):
    await lead(tg, 508, HOT)
    s = await tg.app.act(508, "delete")
    assert s["screen"] == "welcome" and s["consent"] is False
    u, ld = await repo.get_user(508), await repo.get_lead(508)
    assert u.first_name is None and u.deleted_at is not None
    assert ld.phone is None and ld.status == "deleted"
    assert await repo.get_answers(508) == {}
    assert any(e.name == "segment_assigned" for e in await repo.events_since(u.created_at))

    await lead(tg, 518, HOT)
    await tg.text(518, "/delete_me")
    await tg.press(518, "del:yes")
    assert (await repo.get_lead(518)).phone is None


async def test_stats_and_reload(tg, tmp_path, monkeypatch):
    await lead(tg, 600, HOT, start="/start ig")
    await lead(tg, 601, WARM, start="/start ig")
    # бросил на вопросе 3
    await tg.text(610, "/start tg")
    await tg.app.act(610, "consent", value=True)
    await tg.app.act(610, "start")
    await tg.app.act(610, "answer", q="role", a="owner")
    await tg.app.act(610, "answer", q="pain", a="no_time_ops")

    tg.clear()
    await tg.text(ADMIN, "/stats 7")
    out = tg.texts(ADMIN)[-1]
    assert "старты 3 | начали 3 (100%) | завершили 2 (67%) | телефон 2 (67%)" in out
    assert "горячие 1 (50%) от контактов" in out
    assert "— ig" in out and "— tg" in out
    assert "1 — 3. Что должно измениться" in out

    from bot.config import get_settings

    d = tmp_path / "content"
    shutil.copytree(ROOT / "content", d)
    p = d / "questions.yaml"
    p.write_text(p.read_text(encoding="utf-8").replace('text: "Кто вы в компании?"', 'text: "Ваша роль?"'),
                 encoding="utf-8")
    monkeypatch.setattr(get_settings(), "content_dir", d)
    await tg.text(ADMIN, "/reload")
    assert tg.texts(ADMIN)[-1].startswith("Перечитал")
    await tg.text(777, "/start")
    await tg.app.act(777, "consent", value=True)
    assert (await tg.app.act(777, "start"))["question"]["text"] == "Ваша роль?"

    (d / "scoring.yaml").write_text("points: [", encoding="utf-8")
    await tg.text(ADMIN, "/reload")
    assert "прежняя версия" in tg.texts(ADMIN)[-1]


async def test_admin_contacted_button(tg):
    s = await lead(tg, 509, HOT)
    assert s["offer"] is not None
    await tg.press(ADMIN, "adm:contacted:509")
    ld = await repo.get_lead(509)
    assert ld.contacted_at is not None and ld.status == "contacted"
    assert (await tg.app.state(509))["offer"] is None  # после разговора не зовём снова


async def test_non_admin_cannot_send(tg):
    await tg.text(42, "/send 1 hi")
    assert tg.texts(42)[-1] == get_content().t("text_forwarded")


async def test_menu_and_notify_toggle(tg):
    await lead(tg, 520, WARM)
    tg.clear()
    await tg.text(520, "/menu")
    assert tg.sent(520)[-1].reply_markup.inline_keyboard[0][0].web_app.url == "https://app.example"
    s = await tg.app.act(520, "notify", value=False)
    assert s["menu"]["notify_on"] is False
    assert (await repo.get_user(520)).nurture_enabled is False
