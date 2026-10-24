"""Поддельный Telegram для aiogram 3.31: сессия без сети и фабрики настоящих Update/Message/CallbackQuery.

FakeSession наследует BaseSession и переопределяет make_request: вместо HTTP-запроса исходящий вызов проверяется
по правилам Bot API (длина текста, HTML, callback_data ≤ 64 байт, URL кнопок, «message is not modified»,
блокировка бота пользователем) и записывается. Сообщения хранятся по чатам, поэтому нажатие кнопки всегда
строится из актуальной клавиатуры сообщения — ровно как у настоящего клиента.
"""
from __future__ import annotations

import html as htmllib
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from aiogram import Bot
from aiogram.client.default import Default, DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods import TelegramMethod
from aiogram.types import InlineKeyboardMarkup, Message, Update

BOT_TOKEN = "7000000001:AAHsim0000000000000000000000000000000"
BOT_ID = 7_000_000_001
ALLOWED_TAGS = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "a", "code", "pre", "tg-spoiler", "span",
                "blockquote", "tg-emoji"}
_TAG_RE = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9-]*)(\s[^<>]*)?>")
_ENTITY_RE = re.compile(r"&(?:lt|gt|amp|quot|#\d+|#x[0-9a-fA-F]+);")
_STRIP_RE = re.compile(r"<[^>]+>")
MAX_TEXT = 4096
MAX_CALLBACK_TEXT = 200


def html_problems(text: str) -> tuple[list[str], list[str]]:
    """(ошибки, предупреждения) Telegram-HTML: незакрытые и неразрешённые теги, голые «<», «&» без сущности."""
    errors: list[str] = []
    warns: list[str] = []
    stack: list[str] = []
    i = 0
    while True:
        i = text.find("<", i)
        if i < 0:
            break
        m = _TAG_RE.match(text, i)
        if not m:
            errors.append(f"голый '<' в позиции {i}: …{text[max(0, i - 10):i + 15]!r}")
            i += 1
            continue
        closing, name = m.group(1) == "/", m.group(2).lower()
        if name not in ALLOWED_TAGS:
            errors.append(f"неподдерживаемый тег <{name}>")
        elif closing:
            if not stack or stack[-1] != name:
                errors.append(f"закрывающий </{name}> без пары")
            else:
                stack.pop()
        else:
            stack.append(name)
        i = m.end()
    if stack:
        errors.append("не закрыты теги: " + ", ".join(stack))
    bare = _ENTITY_RE.sub("", _STRIP_RE.sub("", text))
    if "&" in bare:
        warns.append("символ '&' без сущности")
    return errors, warns


def plain_text(html_text: str, parse_mode: str | None) -> str:
    """Что пользователь видит в чате: HTML без тегов и с раскрытыми сущностями."""
    if parse_mode and str(parse_mode).upper() == "HTML":
        return htmllib.unescape(_STRIP_RE.sub("", html_text))
    return html_text


def markup_rows(markup: Any) -> list[list[dict]] | None:
    """InlineKeyboardMarkup → [[{'text', 'callback_data'|'url'}]] (None, если клавиатуры нет)."""
    if markup is None:
        return None
    if not isinstance(markup, InlineKeyboardMarkup):
        raise TelegramBadRequest(method=None, message="Bad Request: only inline keyboards are supported by the simulator")  # type: ignore[arg-type]
    rows = []
    for row in markup.inline_keyboard:
        out = []
        for b in row:
            d: dict = {"text": b.text}
            if b.callback_data is not None:
                d["callback_data"] = b.callback_data
            if b.url is not None:
                d["url"] = b.url
            out.append(d)
        rows.append(out)
    return rows


@dataclass
class Stored:
    mid: int
    chat_id: int
    html: str
    text: str
    parse_mode: str | None
    rows: list[list[dict]] | None
    ts: datetime
    from_user: bool = False
    edits: int = 0
    tag: str = ""                      # метка рассылки (digest/plan/feedback/…) — ставит runner

    def buttons(self) -> list[dict]:
        return [b for r in (self.rows or []) for b in r]


class FakeTelegram:
    """Состояние «мира»: чаты, журнал вызовов, нарушения правил Bot API, заблокировавшие бота."""

    def __init__(self, now_fn: Callable[[], datetime] | None = None) -> None:
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self.chats: dict[int, list[Stored]] = defaultdict(list)
        self._by_id: dict[tuple[int, int], Stored] = {}
        self._mid: dict[int, int] = defaultdict(int)
        self.calls: list[dict] = []
        self.violations: list[dict] = []
        self.blocked: set[int] = set()
        self.commands: list[list[dict]] = []
        self.callbacks: dict[str, dict] = {}
        self._cb_seq = 0
        self._update_seq = 0
        self.new_since_drain: list[Stored] = []
        self.fail_plan: list[Exception | None] = []   # план сбоев для ближайших sendMessage: None — отправить нормально
        self.bot: Bot | None = None

    # ── служебное ──
    def next_mid(self, chat_id: int) -> int:
        self._mid[chat_id] += 1
        return self._mid[chat_id]

    def violate(self, code: str, detail: str, chat_id: int | None = None, mid: int | None = None) -> None:
        self.violations.append({"t": self.now_fn().isoformat(), "code": code, "detail": detail, "chat_id": chat_id, "mid": mid})

    def get(self, chat_id: int, mid: int) -> Stored | None:
        return self._by_id.get((chat_id, mid))

    def last_bot_message(self, chat_id: int) -> Stored | None:
        for st in reversed(self.chats[chat_id]):
            if not st.from_user:
                return st
        return None

    def drain_new(self) -> list[Stored]:
        out, self.new_since_drain = self.new_since_drain, []
        return out

    def _record(self, **kw: Any) -> dict:
        rec = {"seq": len(self.calls) + 1, "t": self.now_fn().isoformat(), **kw}
        self.calls.append(rec)
        return rec

    def _store(self, chat_id: int, html_text: str, parse_mode: str | None, rows, from_user: bool = False) -> Stored:
        st = Stored(self.next_mid(chat_id), chat_id, html_text, plain_text(html_text, parse_mode), parse_mode, rows,
                    self.now_fn(), from_user=from_user)
        self.chats[chat_id].append(st)
        self._by_id[(chat_id, st.mid)] = st
        if not from_user:
            self.new_since_drain.append(st)
        return st

    # ── проверки Bot API ──
    def _check_markup(self, method: TelegramMethod, rows, chat_id, mid=None) -> None:
        if rows is None:
            return
        total = sum(len(r) for r in rows)
        if total > 100 or any(len(r) > 8 for r in rows):
            self.violate("markup_too_big", f"кнопок {total}, в ряду до {max(len(r) for r in rows)}", chat_id, mid)
            raise TelegramBadRequest(method=method, message="Bad Request: reply markup is too long")
        for r in rows:
            for b in r:
                if not b["text"]:
                    raise TelegramBadRequest(method=method, message="Bad Request: text buttons are unallowed in the inline keyboard")
                cd, url = b.get("callback_data"), b.get("url")
                if cd is not None and not (1 <= len(cd.encode()) <= 64):
                    self.violate("callback_data_len", f"{len(cd.encode())} байт: {cd[:40]}", chat_id, mid)
                    raise TelegramBadRequest(method=method, message="Bad Request: BUTTON_DATA_INVALID")
                if url is not None:
                    u = urlparse(url)
                    host = (u.hostname or "").lower()
                    if u.scheme not in ("http", "https", "tg") or not host or host in ("localhost", "127.0.0.1") or " " in url:
                        self.violate("button_url_invalid", f"{b['text']}: {url[:80]}", chat_id, mid)
                        raise TelegramBadRequest(method=method, message="Bad Request: BUTTON_URL_INVALID")
                    if len(url) > 2048 and mid is None:      # считаем только отправки, а не повторную проверку при правке клавиатуры
                        self.violate("button_url_long", f"{len(url)} символов у «{b['text']}»", chat_id, mid)
                if cd is None and url is None:
                    raise TelegramBadRequest(method=method, message="Bad Request: BUTTON_TYPE_INVALID")

    def _check_text(self, method: TelegramMethod, html_text: str, parse_mode: str | None, chat_id, mid=None) -> None:
        if not html_text or not html_text.strip():
            raise TelegramBadRequest(method=method, message="Bad Request: message text is empty")
        if parse_mode and str(parse_mode).upper() == "HTML":
            errs, warns = html_problems(html_text)
            for w in warns:
                self.violate("html_warning", w + f": {html_text[:60]!r}", chat_id, mid)
            if errs:
                self.violate("html_parse", "; ".join(errs) + f" | {html_text[:80]!r}", chat_id, mid)
                raise TelegramBadRequest(method=method, message=f"Bad Request: can't parse entities: {errs[0]}")
        if len(plain_text(html_text, parse_mode)) > MAX_TEXT:
            self.violate("text_too_long", f"{len(html_text)} символов", chat_id, mid)
            raise TelegramBadRequest(method=method, message="Bad Request: message is too long")

    # ── обработка методов ──
    @staticmethod
    def _resolve(bot: Bot, v: Any) -> Any:
        return bot.default[v.name] if isinstance(v, Default) else v

    def _message_obj(self, bot: Bot, st: Stored) -> Message:
        return Message.model_validate(self.message_dict(st), context={"bot": bot})

    def message_dict(self, st: Stored) -> dict:
        d: dict = {"message_id": st.mid, "date": int(st.ts.timestamp()), "chat": {"id": st.chat_id, "type": "private"},
                   "text": st.text}
        if st.from_user:
            d["from"] = {"id": st.chat_id, "is_bot": False, "first_name": "Sim"}
        else:
            d["from"] = {"id": BOT_ID, "is_bot": True, "first_name": "Досуг", "username": "leisure_sim_bot"}
            if st.rows is not None:
                d["reply_markup"] = {"inline_keyboard": [[dict(b) for b in r] for r in st.rows]}
        return d

    async def handle(self, bot: Bot, method: TelegramMethod) -> Any:
        name = method.__api_method__
        if name == "sendMessage":
            return self._send(bot, method)
        if name in ("editMessageText", "editMessageReplyMarkup"):
            return self._edit(bot, method, name)
        if name == "answerCallbackQuery":
            return self._answer(bot, method)
        if name == "setMyCommands":
            self.commands.append([{"command": c.command, "description": c.description} for c in method.commands])
            self._record(method="SetMyCommands", n=len(method.commands))
            return True
        self.violate("unsupported_method", name)
        self._record(method=name)
        return True

    def _send(self, bot: Bot, m: Any) -> Message:
        chat_id = int(m.chat_id)
        pm = self._resolve(bot, m.parse_mode)
        pm = pm.value if hasattr(pm, "value") else pm
        rows = markup_rows(m.reply_markup)
        if self.fail_plan:
            exc = self.fail_plan.pop(0)
            if exc is not None:
                self._record(method="SendMessage", chat_id=chat_id, ok=False, error=type(exc).__name__, text=plain_text(m.text, pm)[:80])
                raise exc
        if chat_id in self.blocked:
            self._record(method="SendMessage", chat_id=chat_id, ok=False, error="Forbidden: bot was blocked by the user",
                         text=plain_text(m.text, pm)[:80])
            raise TelegramForbiddenError(method=m, message="Forbidden: bot was blocked by the user")
        try:
            self._check_text(m, m.text, pm, chat_id)
            self._check_markup(m, rows, chat_id)
        except TelegramBadRequest as e:
            self._record(method="SendMessage", chat_id=chat_id, ok=False, error=str(e), text=plain_text(m.text, pm)[:80])
            raise
        st = self._store(chat_id, m.text, pm, rows)
        self._record(method="SendMessage", chat_id=chat_id, message_id=st.mid, ok=True, text=st.text, rows=rows)
        return self._message_obj(bot, st)

    def _edit(self, bot: Bot, m: Any, name: str) -> Message | bool:
        label = "EditMessageText" if name == "editMessageText" else "EditMessageReplyMarkup"
        if m.chat_id is None or m.message_id is None:
            self.violate("inline_edit_unsupported", label)
            return True
        chat_id, mid = int(m.chat_id), int(m.message_id)
        st = self.get(chat_id, mid)
        try:
            if st is None or st.from_user:
                raise TelegramBadRequest(method=m, message="Bad Request: message to edit not found")
            rows = markup_rows(m.reply_markup)
            if name == "editMessageText":
                pm = self._resolve(bot, m.parse_mode)
                pm = pm.value if hasattr(pm, "value") else pm
                self._check_text(m, m.text, pm, chat_id, mid)
                self._check_markup(m, rows, chat_id, mid)
                new_html, new_text = m.text, plain_text(m.text, pm)
                if new_text == st.text and rows == st.rows:
                    raise TelegramBadRequest(method=m, message="Bad Request: message is not modified: specified new message "
                                             "content and reply markup are exactly the same as a current content and reply markup of the message")
                st.html, st.text, st.parse_mode, st.rows = new_html, new_text, pm, rows
            else:
                self._check_markup(m, rows, chat_id, mid)
                if rows == st.rows:
                    raise TelegramBadRequest(method=m, message="Bad Request: message is not modified: specified new message "
                                             "content and reply markup are exactly the same as a current content and reply markup of the message")
                st.rows = rows
        except TelegramBadRequest as e:
            self._record(method=label, chat_id=chat_id, message_id=mid, ok=False, error=str(e).split(": specified")[0])
            raise
        st.edits += 1
        self._record(method=label, chat_id=chat_id, message_id=mid, ok=True, text=st.text if name == "editMessageText" else None,
                     rows=st.rows)
        return self._message_obj(bot, st)

    def _answer(self, bot: Bot, m: Any) -> bool:
        cb = self.callbacks.get(m.callback_query_id)
        text = m.text or ""
        if cb is None or cb["answered"]:
            self._record(method="AnswerCallbackQuery", ok=False, error="query is too old / already answered", text=text)
            self.violate("callback_answered_twice" if cb else "callback_unknown", m.callback_query_id)
            raise TelegramBadRequest(method=m, message="Bad Request: query is too old and response timeout expired or query ID is invalid")
        if len(text) > MAX_CALLBACK_TEXT:
            self.violate("toast_too_long", f"{len(text)} символов")
            raise TelegramBadRequest(method=m, message="Bad Request: MESSAGE_TOO_LONG")
        cb["answered"] = True
        cb["toast"] = text
        self._record(method="AnswerCallbackQuery", ok=True, text=text, alert=bool(m.show_alert))
        return True

    # ── фабрики входящих Update ──
    def _user(self, uid: int, name: str, username: str) -> dict:
        return {"id": uid, "is_bot": False, "first_name": name, "username": username, "language_code": "ru"}

    def message_update(self, bot: Bot, uid: int, name: str, username: str, text: str) -> Update:
        st = self._store(uid, text, None, None, from_user=True)
        self._update_seq += 1
        msg = self.message_dict(st)
        msg["from"] = self._user(uid, name, username)
        msg["chat"] = {"id": uid, "type": "private", "first_name": name, "username": username}
        if text.startswith("/"):
            msg["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
        self._record(method="UserMessage", chat_id=uid, message_id=st.mid, text=text)
        return Update.model_validate({"update_id": self._update_seq, "message": msg}, context={"bot": bot})

    def callback_update(self, bot: Bot, uid: int, name: str, username: str, mid: int, data: str) -> tuple[Update, str]:
        st = self.get(uid, mid)
        if st is None:
            raise KeyError(f"нет сообщения {mid} в чате {uid}")
        self._update_seq += 1
        self._cb_seq += 1
        cb_id = f"cb{self._cb_seq}"
        self.callbacks[cb_id] = {"answered": False, "toast": None, "uid": uid, "mid": mid, "data": data}
        msg = self.message_dict(st)
        msg["chat"] = {"id": uid, "type": "private", "first_name": name, "username": username}
        upd = {"update_id": self._update_seq, "callback_query": {
            "id": cb_id, "from": self._user(uid, name, username), "chat_instance": "sim", "data": data, "message": msg}}
        self._record(method="UserCallback", chat_id=uid, message_id=mid, data=data)
        return Update.model_validate(upd, context={"bot": bot}), cb_id


class FakeSession(BaseSession):
    """Сессия aiogram без сети: все вызовы уходят в FakeTelegram.handle."""

    def __init__(self, world: FakeTelegram) -> None:
        super().__init__()
        self.world = world

    async def close(self) -> None:  # нечего закрывать
        return None

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None) -> Any:
        return await self.world.handle(bot, method)

    async def stream_content(self, url: str, headers: dict | None = None, timeout: int = 30, chunk_size: int = 65536,
                             raise_for_status: bool = True):  # pragma: no cover
        yield b""


def make_bot(world: FakeTelegram, default: DefaultBotProperties | None = None) -> Bot:
    """Настоящий aiogram.Bot с FakeSession. default — свойства, с которыми продукт сам создаёт бота (leisure/bot/main.py)."""
    bot = Bot(BOT_TOKEN, session=FakeSession(world), default=default or DefaultBotProperties(parse_mode=ParseMode.HTML))
    world.bot = bot
    return bot
