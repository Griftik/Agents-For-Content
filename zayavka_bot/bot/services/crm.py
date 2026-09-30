"""Синк лидов в CRM в фоне (п. 7): Google Sheets, webhook amoCRM или ничего.

Очередь с повторами: ошибки Sheets не ломают сценарий, пишутся в лог и админу.
Одна строка на лида, ключ — user_id; строка обновляется при каждом изменении.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from aiogram import Bot

from bot.config import CrmSync, get_settings
from bot.content import get_content
from bot.db import repo
from bot.services import notify
from bot.services.cards import SHEET_COLUMNS, sheet_row

log = logging.getLogger(__name__)

RETRY_DELAYS = [5, 30, 120, 600]


class SheetsBackend:
    def __init__(self, sa_json: str, sheet_id: str, tab: str) -> None:
        self._sa_json, self._sheet_id, self._tab = sa_json, sheet_id, tab
        self._ws = None

    def _worksheet(self):
        if self._ws is None:
            import gspread

            gc = gspread.service_account(filename=self._sa_json)
            sh = gc.open_by_key(self._sheet_id)
            try:
                ws = sh.worksheet(self._tab)
            except gspread.WorksheetNotFound:
                ws = sh.add_worksheet(self._tab, rows=1000, cols=len(SHEET_COLUMNS))
            if ws.row_values(1) != SHEET_COLUMNS:
                ws.update([SHEET_COLUMNS], "A1")
            self._ws = ws
        return self._ws

    def upsert_sync(self, row: list[str]) -> None:
        ws = self._worksheet()
        uid_col = SHEET_COLUMNS.index("user_id") + 1
        ids = ws.col_values(uid_col)
        try:
            n = ids.index(row[uid_col - 1]) + 1
            ws.update([row], f"A{n}", value_input_option="RAW")
        except ValueError:
            ws.append_row(row, value_input_option="RAW")

    async def upsert(self, data: dict[str, Any]) -> None:
        row = sheet_row(get_content(), data)
        await asyncio.to_thread(self.upsert_sync, row)


class WebhookBackend:
    def __init__(self, url: str) -> None:
        self._url = url

    async def upsert(self, data: dict[str, Any]) -> None:
        c = get_content()
        payload = dict(data)
        payload["answers_text"] = {q: c.label(q, a) for q, a in (data.get("answers") or {}).items()}
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(self._url, json=payload)
            r.raise_for_status()


class CrmSyncer:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self.queue: asyncio.Queue[int] = asyncio.Queue()
        self._pending: set[int] = set()
        self._task: asyncio.Task | None = None
        s = get_settings()
        self.backend: SheetsBackend | WebhookBackend | None = None
        if s.crm_sync == CrmSync.google_sheets:
            if not s.google_service_account_json or not s.google_sheet_id:
                log.error("CRM_SYNC=google_sheets, но не заданы GOOGLE_SERVICE_ACCOUNT_JSON / GOOGLE_SHEET_ID")
            else:
                self.backend = SheetsBackend(str(s.google_service_account_json), s.google_sheet_id, s.google_sheet_tab)
        elif s.crm_sync == CrmSync.amocrm_webhook:
            if s.amocrm_webhook_url:
                self.backend = WebhookBackend(s.amocrm_webhook_url)
            else:
                log.error("CRM_SYNC=amocrm_webhook, но не задан AMOCRM_WEBHOOK_URL")

    def push(self, user_id: int) -> None:
        """Поставить лида в очередь. Повторные пуши до обработки схлопываются."""
        if self.backend is None or user_id in self._pending:
            return
        self._pending.add(user_id)
        self.queue.put_nowait(user_id)

    def start(self) -> None:
        if self.backend is not None:
            self._task = asyncio.create_task(self._worker(), name="crm-sync")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _worker(self) -> None:
        while True:
            uid = await self.queue.get()
            self._pending.discard(uid)
            asyncio.create_task(self._sync_with_retry(uid))

    async def _sync_with_retry(self, uid: int) -> None:
        for attempt, delay in enumerate([0, *RETRY_DELAYS]):
            if delay:
                await asyncio.sleep(delay)
            try:
                data = await repo.lead_snapshot(uid)  # свежие данные на момент попытки
                if data:
                    await self.backend.upsert(data)  # type: ignore[union-attr]
                return
            except Exception as e:  # noqa: BLE001
                log.warning("CRM sync user %s попытка %s: %s", uid, attempt + 1, e)
                last = e
        log.error("CRM sync user %s: не удалось после повторов", uid)
        await notify.alert(self.bot, "crm", f"Запись лида в CRM не проходит: {last}. Лид {uid} в БД сохранён.")


_syncer: CrmSyncer | None = None


def init(bot: Bot) -> CrmSyncer:
    global _syncer
    _syncer = CrmSyncer(bot)
    return _syncer


def push(user_id: int) -> None:
    if _syncer is not None:
        _syncer.push(user_id)
