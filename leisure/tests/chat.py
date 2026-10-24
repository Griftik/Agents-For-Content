"""Помощник тестов бота: настоящий диспетчер + поддельный Telegram (leisure.sim.fakebot, проверяет правила Bot API)."""
import asyncio

from leisure.bot.onboarding import markup
from leisure.sim import fakebot

from .conftest import fresh_dispatcher

UID = 999_100_001


class Chat:
    """Диспетчер бота + поддельный Telegram + одна карточка в чате."""

    def __init__(self, uid=UID):
        self.uid, self.world = uid, fakebot.FakeTelegram()
        self.bot = fakebot.make_bot(self.world)
        self.dp = fresh_dispatcher()

    def run(self, coro):
        return asyncio.run(coro)

    async def _send(self, text, rows):
        return await self.bot.send_message(self.uid, text, reply_markup=markup(rows) if rows else None)

    def send(self, text="card", rows=None):
        return self.run(self._send(text, rows)).message_id

    async def _feed(self, upd):
        await self.dp.feed_update(self.bot, upd)

    def press(self, mid, data) -> str:
        upd, cb_id = self.world.callback_update(self.bot, self.uid, "Тест", "tester", mid, data)
        self.run(self._feed(upd))
        return self.world.callbacks[cb_id]["toast"]

    def say(self, text):
        self.run(self._feed(self.world.message_update(self.bot, self.uid, "Тест", "tester", text)))

    def rows(self, mid):
        return [[b["text"] for b in r] for r in self.world.get(self.uid, mid).rows]

    def cbs(self, mid, text_):
        """callback_data кнопки по подписи: точное совпадение, потом по концу и началу (префиксы ✓ / ●, стрелки, счётчики)."""
        btns = [b for r in self.world.get(self.uid, mid).rows for b in r if "callback_data" in b]
        for test in (lambda t: t == text_, lambda t: t.endswith(text_), lambda t: t.startswith(text_), lambda t: text_ in t):
            for b in btns:
                if test(b["text"]):
                    return b["callback_data"]
        raise KeyError(f"нет кнопки «{text_}» среди {[b['text'] for b in btns]}")

    def last_text(self):
        return self.world.last_bot_message(self.uid).text

    def state(self):
        return self.run(self.dp.fsm.get_context(self.bot, self.uid, self.uid).get_state())

    def set_state(self, st):
        self.run(self.dp.fsm.get_context(self.bot, self.uid, self.uid).set_state(st))

    def last_mid(self) -> int:
        return self.world.last_bot_message(self.uid).mid

    def tap(self, mid, label) -> str:
        """Нажать кнопку по подписи (с учётом префиксов ✓ / ●)."""
        return self.press(mid, self.cbs(mid, label))

    def presses(self) -> int:
        """Сколько действий сделал человек: сообщения и нажатия кнопок (так считает отчёт симулятора)."""
        return sum(1 for c in self.world.calls if c.get("method") in ("UserMessage", "UserCallback"))

    def texts(self) -> list[str]:
        return [m.text for m in self.world.chats[self.uid] if not m.from_user]
