"""Отложенные задания из таблицы scheduled_jobs. Переживают рестарт (п. 13).

Виды: таймаут контакта (10 минут, п. 3.4), два напоминания горячим (п. 3.7),
окончание платной подписки. Напоминания о слотах — полная версия.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot

from bot.content import get_content
from bot.db import repo
from bot.db.models import ScheduledJob
from bot.keyboards import kb
from bot.services import flow, leadflow
from bot.services import subscription as sub

log = logging.getLogger(__name__)
TICK_SEC = 20


async def handle(bot: Bot, job: ScheduledJob) -> None:
    uid = job.user_id
    if uid is None:
        return
    u = await repo.get_user(uid)
    if u is None or u.deleted_at is not None:
        return
    c = get_content()

    if job.kind == "contact_timeout":
        # телефон не оставили за N минут — разбор всё равно готовим, contact = none
        if u.stage == flow.STAGE_CONTACT:
            await repo.log_event(uid, "contact_skipped", reason="timeout")
            await leadflow.finalize(bot, uid)
        elif u.stage == flow.STAGE_COMPANY:
            await leadflow.finalize(bot, uid)
        return

    if job.kind in leadflow.HOT_REMINDERS:
        lead = await repo.get_lead(uid)
        if not lead or lead.segment != "hot" or lead.contacted_at or not u.nurture_enabled:
            return
        await bot.send_message(uid, c.t(job.kind), reply_markup=kb.book(c.t("hot_button")))
        if job.kind == "hot_reminder_72h":
            # не записался за 72 часа — дальше получает только важное из канала, как тёплые
            await repo.update_lead(uid, status="hot_to_warm")
        return

    if job.kind in (sub.JOB_EXPIRING, sub.JOB_EXPIRED):
        await sub.handle_job(bot, uid, job.kind)
        return

    log.warning("неизвестный вид задания %s", job.kind)


async def run(bot: Bot) -> None:
    while True:
        try:
            for job in await repo.take_due_jobs():
                try:
                    await handle(bot, job)
                except Exception as e:  # noqa: BLE001
                    log.exception("задание %s (%s) упало", job.id, job.kind)
                    await repo.mark_job(job.id, "failed", str(e)[:500])
        except Exception:  # noqa: BLE001
            log.exception("планировщик: ошибка цикла")
        await asyncio.sleep(TICK_SEC)
