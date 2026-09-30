"""Серия для тёплых (раздел 8): рабочее время, выбор варианта, старт, остановка, отправка."""
from __future__ import annotations

import shutil
from datetime import datetime, timedelta

import pytest
import yaml
from sqlalchemy import update

from bot.config import get_settings
from bot.content import ContentError, get_content, load_content, reload_content
from bot.db import repo
from bot.db.models import ScheduledJob, utcnow
from bot.db.session import session
from bot.services import nurture, scheduler
from tests.conftest import ADMIN, ROOT
from tests.test_scenarios import HOT, WARM, fill, tg  # noqa: F401 — фикстура tg

# --- рабочее время (МСК = UTC+3) -------------------------------------------


@pytest.mark.parametrize("utc,expected_utc", [
    ("2026-10-05 09:00", "2026-10-05 09:00"),   # 12:00 МСК — как есть
    ("2026-10-05 05:30", "2026-10-05 07:00"),   # 08:30 МСК → 10:00 того же дня
    ("2026-10-05 16:00", "2026-10-06 07:00"),   # 19:00 МСК → 10:00 следующего
    ("2026-10-05 22:00", "2026-10-06 07:00"),   # 01:00 МСК следующего дня → 10:00
    ("2026-10-05 15:59", "2026-10-05 15:59"),   # 18:59 МСК — ещё можно
])
def test_work_time(utc, expected_utc):
    f = "%Y-%m-%d %H:%M"
    assert nurture.work_time(datetime.strptime(utc, f)) == datetime.strptime(expected_utc, f)


def test_pick_variant_priority():
    step = {
        "by_session_type": {"goal": {"text": "про цель"}, "sync": {"text": ""}},
        "by_pain": {"no_initiative": {"text": "про инициативу"}},
        "default": {"text": "общий"},
    }
    assert nurture.pick_variant(step, "goal", {"pain": "no_initiative"})["text"] == "про цель"
    # пустой вариант по типу → вариант по боли
    assert nurture.pick_variant(step, "sync", {"pain": "no_initiative"})["text"] == "про инициативу"
    assert nurture.pick_variant(step, "revenue", {"pain": "scale_unknown"})["text"] == "общий"
    assert nurture.pick_variant({"default": {"text": " "}}, None, {}) == {}
    assert nurture.pick_variant({"default": {"file": "nurture/a.pdf"}}, None, {})["file"] == "nurture/a.pdf"


def test_structure_matches_tz(content):
    steps = content.nurture["steps"]
    assert [s["delay_days"] for s in steps] == [3, 8, 14, 21, 45]
    assert [s["button"] for s in steps] == ["booking", "booking", "booking", "booking_time", "none"]


def test_validation(tmp_path):
    d = tmp_path / "content"
    shutil.copytree(ROOT / "content", d)
    data = yaml.safe_load((d / "nurture.yaml").read_text(encoding="utf-8"))
    data["steps"][0]["by_session_type"]["nonexistent"] = {"text": "x"}
    data["steps"][1]["delay_days"] = 1  # меньше предыдущего
    (d / "nurture.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ContentError) as e:
        load_content(d)
    assert "nonexistent" in str(e.value) and "delay_days" in str(e.value)


# --- сценарии --------------------------------------------------------------


def _with_texts(tmp_path, monkeypatch, file_for_d8: bool = False):
    """Копия content/ с заполненными текстами серии."""
    d = tmp_path / "content"
    shutil.copytree(ROOT / "content", d)
    data = yaml.safe_load((d / "nurture.yaml").read_text(encoding="utf-8"))
    for st in data["steps"]:
        st["default"] = {"text": f"Шаг {st['id']}: {{pain_text}}"}
    data["steps"][0]["by_session_type"]["goal"] = {"text": "Кейс про цель"}
    if file_for_d8:
        (d / "nurture" / "check.pdf").write_bytes(b"%PDF-1.4")
        data["steps"][1]["by_pain"]["projects_not_done"] = {"text": "Чек-лист", "file": "nurture/check.pdf"}
    (d / "nurture.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(get_settings(), "content_dir", d)
    reload_content(d)


async def _run_due(tg, kind: str | None = None) -> None:
    async with session() as s:
        q = update(ScheduledJob).where(ScheduledJob.status == "pending")
        if kind:
            q = q.where(ScheduledJob.kind == kind)
        await s.execute(q.values(run_at=utcnow() - timedelta(seconds=1)))
        await s.commit()
    for job in await repo.take_due_jobs(limit=100):
        await scheduler.handle(tg.bot, job)


async def _warm_with_report(tg, uid: int) -> None:
    await tg.text(uid, "/start ig")
    await fill(tg, uid, WARM)
    await tg.contact(uid, "+79161234567")
    await tg.press(uid, "company:skip")
    await tg.text(ADMIN, f"/send {uid} Разбор")


async def test_series_starts_after_report_in_work_hours(tg, tmp_path, monkeypatch):  # noqa: F811
    _with_texts(tmp_path, monkeypatch)
    uid = 701
    await _warm_with_report(tg, uid)
    jobs = await repo.pending_jobs(uid, "nurture")
    assert [j.payload["step"] for j in jobs] == ["d3_case", "d8_material", "d14_objection", "d21_personal", "d45_check"]
    for j in jobs:
        msk_hour = (j.run_at + timedelta(hours=3)).hour
        assert 10 <= msk_hour < 19
    first = jobs[0].run_at - utcnow()
    assert timedelta(days=2, hours=12) < first < timedelta(days=4)
    assert (await repo.get_lead(uid)).status == "nurture"


async def test_series_sends_all_steps_and_goes_dormant(tg, tmp_path, monkeypatch):  # noqa: F811
    _with_texts(tmp_path, monkeypatch, file_for_d8=True)
    uid = 702
    await _warm_with_report(tg, uid)
    tg.clear()
    await _run_due(tg, "nurture")

    texts = tg.texts(uid)
    # WARM: стратегия «в голове» → тип goal → вариант по типу сессии
    assert "Кейс про цель" in texts
    # d8 — файл с подписью по боли
    doc = tg.sent(uid, "SendDocument")[0]
    assert doc.caption == "Чек-лист"
    assert doc.reply_markup.inline_keyboard[0][0].callback_data == "book"
    assert "Шаг d21_personal: проекты со стратсессий не реализуются" in texts
    last = [m for m in tg.sent(uid) if m.text.startswith("Шаг d45_check")][0]
    assert last.reply_markup is None  # «как дела?» без кнопки
    lead = await repo.get_lead(uid)
    assert lead.status == "dormant"
    sent = [e for e in await repo.events_since(utcnow() - timedelta(hours=1)) if e.name == "nurture_sent"]
    assert len(sent) == 5


async def test_empty_step_is_skipped_with_alert(tg):  # noqa: F811
    uid = 703  # тексты серии в репозитории пока пустые
    await _warm_with_report(tg, uid)
    tg.clear()
    await _run_due(tg, "nurture")
    assert tg.texts(uid) == []  # пустых сообщений человеку не уходит
    assert any("Шаг серии «d3_case» пропущен" in t for t in tg.texts(ADMIN))
    assert (await repo.get_lead(uid)).status == "dormant"


@pytest.mark.parametrize("how", ["text", "contacted", "menu_off"])
async def test_series_stops(tg, tmp_path, monkeypatch, how):  # noqa: F811
    _with_texts(tmp_path, monkeypatch)
    uid = 710
    await _warm_with_report(tg, uid)
    if how == "text":
        await tg.text(uid, "Спасибо, подумаю")
    elif how == "contacted":
        await tg.press(ADMIN, f"adm:contacted:{uid}")
    else:
        await tg.press(uid, "menu:notify")
    assert await repo.pending_jobs(uid, "nurture") == []
    tg.clear()
    await _run_due(tg)
    assert not any(t.startswith("Шаг") for t in tg.texts(uid))


async def test_hot_without_booking_moves_to_series(tg, tmp_path, monkeypatch):  # noqa: F811
    _with_texts(tmp_path, monkeypatch)
    uid = 720
    await tg.text(uid, "/start")
    await fill(tg, uid, HOT)
    await tg.contact(uid, "+79161234567")
    await tg.press(uid, "company:skip")
    assert await repo.pending_jobs(uid, "nurture") == []
    await _run_due(tg, "hot_reminder_24h")
    await _run_due(tg, "hot_reminder_72h")
    assert get_content().t("hot_reminder_72h") in tg.texts(uid)
    assert len(await repo.pending_jobs(uid, "nurture")) == 5


async def test_specialist_and_hot_report_do_not_start_series(tg):  # noqa: F811
    uid = 730
    await tg.text(uid, "/start")
    await fill(tg, uid, HOT)
    await tg.contact(uid, "+79161234567")
    await tg.press(uid, "company:skip")
    await tg.text(ADMIN, f"/send {uid} Разбор")
    assert await repo.pending_jobs(uid, "nurture") == []  # горячему — сначала разговор, не серия
