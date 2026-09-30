"""Серия для тёплых (раздел 8 ТЗ): content/nurture.yaml → задания в scheduled_jobs.

Все шаги ставятся в очередь сразу при старте серии, время каждого сдвигается в рабочие часы
по Москве. Перед отправкой шаг ещё раз проверяет, что серия не остановлена.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from aiogram import Bot
from aiogram.types import FSInputFile

from bot.config import get_settings
from bot.content import Content, get_content
from bot.db import repo
from bot.db.models import utcnow
from bot.keyboards import kb
from bot.services import crm, notify
from bot.services.cards import pain_text

log = logging.getLogger(__name__)

KIND = "nurture"
MSK = timezone(timedelta(hours=3))
NURTURE_SEGMENTS = {"warm", "warm_initiator", "hot"}  # hot — после 72 ч без записи
CAPTION_LIMIT = 1024


def work_time(run_at_utc: datetime, start_h: int = 10, end_h: int = 19) -> datetime:
    """Сдвинуть время (naive UTC) в рабочие часы МСК: ночь и вечер → ближайшее утро."""
    msk = run_at_utc.replace(tzinfo=timezone.utc).astimezone(MSK)
    if msk.hour < start_h:
        msk = msk.replace(hour=start_h, minute=0, second=0, microsecond=0)
    elif msk.hour >= end_h:
        msk = (msk + timedelta(days=1)).replace(hour=start_h, minute=0, second=0, microsecond=0)
    return msk.astimezone(timezone.utc).replace(tzinfo=None)


def _hours(c: Content) -> tuple[int, int]:
    wh = (c.nurture or {}).get("work_hours") or {}
    return int(wh.get("start", 10)), int(wh.get("end", 19))


def steps(c: Content) -> list[dict[str, Any]]:
    return list((c.nurture or {}).get("steps") or [])


def pick_variant(step: Mapping[str, Any], session_type: str | None, answers: Mapping[str, str]) -> dict[str, Any]:
    """Вариант шага: по типу сессии → по боли → default/сам шаг. Пустые варианты пропускаются."""
    candidates = [
        (step.get("by_session_type") or {}).get(session_type or ""),
        (step.get("by_pain") or {}).get(answers.get("pain") or ""),
        step.get("default"),
        {"text": step.get("text"), "file": step.get("file")},
    ]
    for v in candidates:
        if v and (str(v.get("text") or "").strip() or v.get("file")):
            return dict(v)
    return {}


async def start(user_id: int) -> int:
    """Запустить серию заново с текущего момента. Возвращает число поставленных шагов."""
    c = get_content()
    await repo.cancel_jobs(user_id, [KIND])
    now, (h1, h2) = utcnow(), _hours(c)
    n = 0
    for st in steps(c):
        run_at = work_time(now + timedelta(days=float(st["delay_days"])), h1, h2)
        await repo.schedule_at(user_id, KIND, run_at, step=str(st["id"]))
        n += 1
    if n:
        await repo.update_lead(user_id, status="nurture")
        crm.push(user_id)
    return n


async def stop(user_id: int) -> None:
    await repo.cancel_jobs(user_id, [KIND])


async def send_step(bot: Bot, user_id: int, step_id: str) -> None:
    c = get_content()
    all_steps = steps(c)
    step = next((s for s in all_steps if str(s.get("id")) == step_id), None)
    if step is None:
        log.warning("шаг серии %s не найден в nurture.yaml — пропущен", step_id)
        return
    u = await repo.get_user(user_id)
    lead = await repo.get_lead(user_id)
    if (u is None or u.deleted_at is not None or not u.nurture_enabled or lead is None
            or lead.contacted_at is not None or lead.segment not in NURTURE_SEGMENTS):
        return
    is_last = step is all_steps[-1]
    answers = await repo.get_answers(user_id)
    v = pick_variant(step, lead.session_type, answers)

    if not v:
        await notify.alert(
            bot, f"nurture_empty:{step_id}",
            f"Шаг серии «{step_id}» пропущен: в content/nurture.yaml нет текста. Заполните и отправьте /reload.",
            every_sec=24 * 3600,
        )
    else:
        await _send(bot, user_id, step, v, c, name=u.first_name or "", pain=pain_text(c, answers))
        await repo.log_event(user_id, "nurture_sent", step=step_id)

    if is_last:
        await repo.update_lead(user_id, status="dormant")
        crm.push(user_id)


async def _send(bot: Bot, uid: int, step: Mapping[str, Any], v: Mapping[str, Any], c: Content,
                *, name: str, pain: str) -> None:
    text = str(v.get("text") or "").strip().format_map(_Keep(name=name, pain_text=pain))
    button = step.get("button", "booking")
    markup = None
    if button == "booking":
        markup = kb.book(c.t("warm_button"))
    elif button == "booking_time":
        markup = kb.book(c.t("hot_button"))

    file = v.get("file")
    if file:
        path = Path(str(file))
        if not path.is_absolute():
            path = get_settings().content_dir / path
        if path.exists():
            caption_fits = len(text) <= CAPTION_LIMIT
            await _send_file(bot, uid, path, caption=text if caption_fits and text else None,
                             markup=markup if caption_fits or not text else None)
            if text and not caption_fits:
                await bot.send_message(uid, text, reply_markup=markup)
            return
        log.warning("файл серии %s не найден", path)
        await notify.alert(bot, f"nurture_file:{file}", f"Файл серии не найден: content/{file}")
        if not text:
            return
    await bot.send_message(uid, text, reply_markup=markup, disable_web_page_preview=True)


async def _send_file(bot: Bot, uid: int, path: Path, caption: str | None, markup) -> None:
    ext = path.suffix.lower()
    f = FSInputFile(path)
    if ext in {".jpg", ".jpeg", ".png", ".webp"}:
        await bot.send_photo(uid, f, caption=caption, reply_markup=markup)
    elif ext in {".mp4", ".mov"}:
        await bot.send_video(uid, f, caption=caption, reply_markup=markup)
    else:
        await bot.send_document(uid, f, caption=caption, reply_markup=markup)


class _Keep(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"
