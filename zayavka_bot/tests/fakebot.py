"""Бот с подменённой HTTP-сессией: запросы к Telegram записываются, ответы синтезируются.

Позволяет гонять настоящий Dispatcher со всеми роутерами и проверять, что ушло пользователю и админу.
"""
from __future__ import annotations

import itertools
import typing
from datetime import datetime, timezone
from typing import Any

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import (
    CallbackQuery,
    Chat,
    Contact,
    Message,
    MessageId,
    Update,
    User,
)

_ids = itertools.count(1)


class RecordingSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod] = []

    async def close(self) -> None:  # noqa: D401
        pass

    async def stream_content(self, *a, **kw):  # pragma: no cover
        raise NotImplementedError

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None) -> Any:
        self.calls.append(method)
        ret = method.__returning__
        types = typing.get_args(ret) or (ret,)
        chat_id = getattr(method, "chat_id", 0) or 0
        if Message in types:
            return Message(
                message_id=next(_ids), date=datetime.now(timezone.utc),
                chat=Chat(id=int(chat_id), type="private"), text=getattr(method, "text", None),
            ).as_(bot)
        if MessageId in types:
            return MessageId(message_id=next(_ids))
        if ret is bool or bool in types:
            return True
        if ret is User:
            return User(id=1, is_bot=True, first_name="bot", username="strategy_diag_bot")
        return True


class FakeTelegram:
    def __init__(self, dp, bot: Bot, session: RecordingSession) -> None:
        self.dp, self.bot, self.session = dp, bot, session
        self._uid = itertools.count(1)

    def sent(self, chat_id: int | None = None, method: str = "SendMessage") -> list[TelegramMethod]:
        return [m for m in self.session.calls if type(m).__name__ == method
                and (chat_id is None or getattr(m, "chat_id", None) == chat_id)]

    def texts(self, chat_id: int) -> list[str]:
        return [m.text for m in self.sent(chat_id)]  # type: ignore[attr-defined]

    def last_markup(self, chat_id: int):
        for m in reversed(self.session.calls):
            if getattr(m, "chat_id", None) == chat_id and getattr(m, "reply_markup", None) is not None:
                return m.reply_markup  # type: ignore[attr-defined]
        return None

    def clear(self) -> None:
        self.session.calls.clear()

    def _user(self, uid: int, username: str | None = None) -> User:
        return User(id=uid, is_bot=False, first_name=f"U{uid}", username=username)

    def _msg(self, uid: int, **kw) -> Message:
        return Message(message_id=next(_ids), date=datetime.now(timezone.utc),
                       chat=Chat(id=uid, type="private"), from_user=self._user(uid, kw.pop("username", None)), **kw)

    async def text(self, uid: int, text: str, **kw) -> None:
        await self.dp.feed_update(self.bot, Update(update_id=next(self._uid), message=self._msg(uid, text=text, **kw)))

    async def contact(self, uid: int, phone: str, owner: int | None = None) -> None:
        c = Contact(phone_number=phone, first_name="x", user_id=owner or uid)
        await self.dp.feed_update(self.bot, Update(update_id=next(self._uid), message=self._msg(uid, contact=c)))

    async def document(self, uid: int, file_id: str = "FILE") -> None:
        from aiogram.types import Document

        await self.dp.feed_update(self.bot, Update(update_id=next(self._uid), message=self._msg(
            uid, document=Document(file_id=file_id, file_unique_id=file_id))))

    async def press(self, uid: int, data: str) -> None:
        msg = self._msg(uid, text="(prev)")
        cb = CallbackQuery(id=str(next(self._uid)), from_user=self._user(uid), chat_instance="x",
                           data=data, message=msg)
        await self.dp.feed_update(self.bot, Update(update_id=next(self._uid), callback_query=cb))
