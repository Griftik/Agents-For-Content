"""Поведение виртуальных людей: онбординг, реакция на дайджест, оценки, команды.

Все действия — только через Dispatcher.feed_update. Кнопки берутся из клавиатуры последнего сообщения бота
(или конкретной карточки): человек читает подписи, а не знает callback_data. Исключение — event_id в служебных
записях для сверки с БД, он никогда не подставляется в нажатие.
"""
from __future__ import annotations

import random
import re
from zoneinfo import ZoneInfo
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from aiogram import Bot
from aiogram.dispatcher.event.bases import UNHANDLED

from leisure.core.catalog import ALL_CATS, SLOTS, VALUE_SHORT, VALUES, cat_label, default_aesthetics
from leisure.core.timeutil import MONTHS

from .fakebot import FakeTelegram, Stored
from .personas import Persona, sigmoid
from leisure.bot.keyboards import BUDGETS, REASON_LABEL

BUDGET_LABEL = dict(BUDGETS)          # {0: "Не важно", 1000: "до 1 000 ₽", 2500: …, 5000: …}
NUDGE_START = "Уже второй раз"        # начало подсказки про бюджет после второго «Мимо — дорого»
LEVEL_OF_LABEL = {"—": 0, "иногда": 1, "интересно": 2, "в первую очередь": 3}
BACK_RE = re.compile(r"назад|отмен|вернуть|← |изменить|исправ", re.I)
DAY_RE = re.compile(r"^(?:(Пятница|Суббота|Воскресенье), )?(\d{1,2}) (" + "|".join(MONTHS) + r")\b")
ERROR_TOAST = "Что-то пошло не так, попробуй ещё раз."


def cb_short(data: str) -> str:
    """callback_data без случайного uuid события — чтобы в отчёте не было нестабильных строк."""
    parts = data.split(":")
    return f"{parts[0]}:{parts[1]}:…" if len(parts) == 3 and len(parts[2]) > 12 else data


class Findings:
    """Счётчики и первые примеры наблюдений. Пример — одна строка с временем, пользователем и фактом из лога."""

    def __init__(self, keep: int = 6) -> None:
        self.keep = keep
        self.count: Counter = Counter()
        self.examples: dict[str, list[str]] = {}
        self.users: dict[str, set] = {}
        self.ignore: set[int] = set()          # приглашённые и пришедшие по ссылке: их наблюдения в основные счётчики не идут
        self.guest_count: Counter = Counter()

    def add(self, code: str, msg: str, uid: int | None = None, t: datetime | None = None, n: int = 1) -> None:
        if uid is not None and uid in self.ignore:
            self.guest_count[code] += n
            return
        self.count[code] += n
        if uid is not None:
            self.users.setdefault(code, set()).add(uid)
        ex = self.examples.setdefault(code, [])
        if len(ex) < self.keep:
            stamp = t.strftime("%d.%m %H:%MZ") if t else ""
            ex.append(" ".join(x for x in (stamp, f"u{uid}" if uid is not None else "", msg) if x))

    def to_dict(self) -> dict:
        return {c: {"count": n, "users": len(self.users.get(c, ())), "examples": self.examples.get(c, [])}
                for c, n in sorted(self.count.items())}


@dataclass
class CardRec:
    mid: int
    event_id: str
    title: str
    day: str | None          # ISO-дата из текста карточки
    in_weekend: bool         # карточка с названием дня недели (слот), а не «на горизонте»
    time_text: str
    buttons: list[str]
    has_days: bool = False   # в карточке есть ряд выбора дня «Пт / Сб / Вс»


@dataclass
class DigestRec:
    uid: int
    week: int | None         # индекс уикенда (0 = 23–25.10.2026)
    origin: str              # first | weekly | manual | reset
    t: str
    cycle: int
    header_mid: int
    header: str
    cards: list[CardRec] = field(default_factory=list)
    opened: bool = False
    decisions: int = 0
    go: int = 0
    already_started: int = 0     # карточки событий, которые к моменту отправки уже начались
    messy_time: int = 0          # карточки, где вместо времени дня — сырой текст источника с несколькими датами
    resent_no_status: int = 0    # карточки с уже принятым решением, пришедшие без отметки ●


@dataclass
class PState:
    p: Persona
    rng: random.Random
    E: float
    status: str = "new"            # new | onboarding | abandoned | active | churned | deleted
    taps: int = 0                  # все действия пользователя (сообщения и нажатия) с первого /start
    onb: dict = field(default_factory=dict)
    first_go_taps: int | None = None
    first_go_cycle: int | None = None
    active_cycles: set = field(default_factory=set)
    digest_cycles: set = field(default_factory=set)
    digests: list[DigestRec] = field(default_factory=list)
    decisions: dict = field(default_factory=dict)       # event_id -> {"status", "reason", "week", "card_day", "rating"}
    ratings: list = field(default_factory=list)
    misclick_done: bool = False
    churn_cycle: int | None = None
    onboarded_t: datetime | None = None
    last_digest: DigestRec | None = None
    open_reasons: int | None = None     # mid карточки, на которой остался открытый блок причин «Мимо»


def parse_card(st: Stored) -> CardRec | None:
    btn = next((b for b in st.buttons() if str(b.get("callback_data", "")).startswith("d:g:")), None)
    if btn is None:
        return None
    lines = st.text.split("\n")
    day = None
    in_weekend = False
    time_text = ""
    if len(lines) > 1:
        m = DAY_RE.match(lines[1])
        if m:
            in_weekend = m.group(1) is not None
            day = f"2026-{MONTHS.index(m.group(3)) + 1:02d}-{int(m.group(2)):02d}"
            time_text = lines[1][m.end():].lstrip(", ")
    return CardRec(st.mid, btn["callback_data"].split(":")[2], lines[0], day, in_weekend, time_text,
                   [b["text"] for b in st.buttons()],
                   any(str(b.get("callback_data", "")).startswith("y:") for b in st.buttons()))


class Driver:
    """Один общий драйвер на всех персон: держит диспетчер, мир, часы и журнал."""

    def __init__(self, world: FakeTelegram, bot: Bot, get_dp: Callable[[], Any], clock, findings: Findings,
                 events: dict[str, dict], cycle_of: Callable[[datetime], int]) -> None:
        self.world, self.bot, self.get_dp, self.clock, self.f = world, bot, get_dp, clock, findings
        self.events = events
        self.cycle_of = cycle_of
        self.log: list[dict] = []
        self.taps: list[dict] = []           # решения и оценки
        self.commands: list[dict] = []
        self.updates = 0
        self.handler_errors = 0
        self.on_going: Callable[[PState, CardRec], None] | None = None        # «иду» нажато: социальный граф решает, звать ли друга
        self.on_rated: Callable[[PState, int, list], None] | None = None      # оценка поставлена: момент рекомендации
        self.on_same_day_go: Callable[[PState], None] | None = None   # «иду» на сегодня после 09:00 — воркер напомнит на ближайшем часовом запуске

    # ───────── базовые операции ─────────
    def _log(self, ps: PState, kind: str, **kw: Any) -> None:
        self.log.append({"t": self.clock.now.isoformat(), "u": ps.p.user_id, "k": kind, **kw})

    async def _feed(self, ps: PState, upd, cb_id: str | None, what: str, mid: int | None = None) -> dict:
        self.updates += 1
        ps.taps += 1
        ps.active_cycles.add(self.cycle_of(self.clock.now))
        exc = handled = None
        try:
            res = await self.get_dp().feed_update(self.bot, upd)
            handled = res is not UNHANDLED
        except Exception as e:  # noqa: BLE001 — исключение обработчика бота: дефект продукта
            exc = f"{type(e).__name__}: {e}"
            self.handler_errors += 1
            self.f.add("handler_exception", f"{what} → {exc[:160]}", ps.p.user_id, self.clock.now)
        cb = self.world.callbacks.get(cb_id) if cb_id else None
        out = {"handled": handled, "exc": exc, "answered": cb["answered"] if cb else None, "toast": cb["toast"] if cb else None}
        if cb is not None and not cb["answered"]:
            self.f.add("callback_unanswered", f"{what}: handled={handled}", ps.p.user_id, self.clock.now)
        if cb is not None and cb["toast"] == ERROR_TOAST:
            self.f.add("error_toast", f"{what} → «{ERROR_TOAST}»", ps.p.user_id, self.clock.now)
        self._log(ps, "update", what=what, **out)
        if ps.open_reasons is not None and ps.open_reasons != mid:      # следующее действие не на этой карточке: блок причин должен свернуться
            st0 = self.world.get(ps.p.user_id, ps.open_reasons)
            still = st0 is not None and any(str(b.get("callback_data", "")).startswith("r:") for b in st0.buttons())
            self.f.add("reasons_not_collapsed" if still else "reasons_collapsed",
                       f"после следующего действия ({what[:40]}) блок причин «Мимо» " + ("остался на карточке" if still else "свернулся"),
                       ps.p.user_id, self.clock.now)
            ps.open_reasons = None
        return out

    async def say(self, ps: PState, text: str) -> dict:
        p = ps.p
        upd = self.world.message_update(self.bot, p.user_id, p.name, p.username, text)
        return await self._feed(ps, upd, None, f"сообщение {text[:30]!r}")

    async def tap(self, ps: PState, st: Stored, btn: dict, why: str = "") -> dict:
        p = ps.p
        if "callback_data" not in btn:
            raise ValueError(f"кнопка без callback_data: {btn}")
        upd, cb_id = self.world.callback_update(self.bot, p.user_id, p.name, p.username, st.mid, btn["callback_data"])
        res = await self._feed(ps, upd, cb_id, f"нажатие «{btn['text']}» ({cb_short(btn['callback_data'])}) {why}".strip(), mid=st.mid)
        return res

    def screen(self, ps: PState) -> Stored | None:
        """Последнее сообщение бота с клавиатурой: подсказки без кнопок («Здесь нужно нажать кнопку выше») экраном не считаются."""
        for st in reversed(self.world.chats[ps.p.user_id]):
            if not st.from_user and st.rows:
                return st
        return None

    @staticmethod
    def find(st: Stored | None, pred: Callable[[str], bool]) -> dict | None:
        if st is None:
            return None
        for b in st.buttons():
            if "callback_data" in b and pred(b["text"]):
                return b
        return None

    def _stuck(self, ps: PState, step: str, want: str) -> None:
        st = self.screen(ps)
        btns = [b["text"] for b in st.buttons()] if st else []
        self.f.add("missing_button", f"шаг «{step}»: нужной кнопки «{want}» нет; экран: {(st.text[:50] if st else '—')!r}, кнопки: {btns[:6]}",
                   ps.p.user_id, self.clock.now)
        ps.status = "abandoned"
        ps.onb["stuck"] = f"{step}:{want}"

    def _check_back(self, ps: PState, step: str) -> bool:
        st = self.screen(ps)
        has = bool(st) and any(BACK_RE.search(b["text"]) for b in st.buttons())
        seen = ps.onb.setdefault("screens", {})
        seen[step] = has
        return has

    # ───────── онбординг ─────────
    def _abandon(self, ps: PState, step: str, sub: int = 0) -> str:
        ps.status = "abandoned"
        ps.onb["abandoned_at"] = step
        ps.onb["abandoned_sub"] = sub
        ps.onb["last_mid"] = (self.screen(ps).mid if self.screen(ps) else None)
        return "abandoned"

    async def onboard(self, ps: PState, command: str = "/start") -> str:
        """Онбординг v2: приветствие → «Шаг 1 из 2» ценности → «Шаг 2 из 2» интересы → подборка. Возвращает completed | abandoned | stuck."""
        p = ps.p
        ps.status = "onboarding"
        ps.onb.setdefault("started", self.clock.now.isoformat())
        ps.onb.setdefault("taps_at_start", ps.taps)
        steps_taps: dict[str, int] = ps.onb.setdefault("steps", {})
        mark = ps.taps

        def close(step: str) -> None:
            nonlocal mark
            steps_taps[step] = steps_taps.get(step, 0) + ps.taps - mark
            mark = ps.taps

        async def noise(step: str) -> None:
            if p.noise_step == step and not ps.onb.get("noise_done"):
                ps.onb["noise_done"] = True
                before = len(self.world.chats[p.user_id])
                res = await self.say(ps, "а что тут нужно сделать? не понял")
                replies = [m for m in self.world.chats[p.user_id][before:] if not m.from_user]
                if not replies:
                    self.f.add("text_ignored", f"на шаге «{step}» бот молчит в ответ на текст «а что тут нужно сделать?» "
                               f"(handled={res['handled']})", p.user_id, self.clock.now)
                    ps.onb["text_ignored"] = ps.onb.get("text_ignored", 0) + 1
                else:
                    self.f.add("text_answered", f"на шаге «{step}» текст получил ответ: «{replies[0].text[:50]}»", p.user_id, self.clock.now)

        await self.say(ps, command)
        st = self.screen(ps)
        if st is None or not st.buttons():
            self._stuck(ps, "consent", "ответ на " + command)
            return "stuck"
        if p.abandon_step == "consent" and not ps.onb.get("abandon_used"):
            ps.onb["abandon_used"] = True
            close("consent")
            return self._abandon(ps, "consent")
        btn = self.find(st, lambda t: t.startswith("Принять"))
        if btn is None:
            self._stuck(ps, "consent", "Принять и начать")
            return "stuck"
        await self.tap(ps, st, btn)
        close("consent")

        # ── Шаг 1 из 2: пять ценностей (по 19) ──
        st = self.screen(ps)
        self._check_back(ps, "values")
        await noise("values")
        picks = list(p.top_values)
        wrong = None
        if p.misclick_step == "values" and not ps.misclick_done:
            wrong = next(v for v in VALUES if v not in picks)       # по ошибке нажал соседнюю ценность вместо последней
            picks = picks[:-1] + [wrong]

        async def pick(v: str) -> bool:
            s = self.screen(ps)
            b = self.find(s, lambda t, v=v: t.removeprefix("✓ ") == VALUE_SHORT.get(v, v))
            if b is None:
                self._stuck(ps, "values", v)
                return False
            await self.tap(ps, s, b, f"ценность {v}")
            return True

        for i, v in enumerate(picks):
            if p.abandon_step == "values" and i == p.abandon_sub and not ps.onb.get("abandon_used"):
                ps.onb["abandon_used"] = True
                close("values")
                return self._abandon(ps, "values", i)
            if not await pick(v):
                return "stuck"
        s = self.screen(ps)
        if s is not None and "Шаг 1 из 2" not in s.text:                 # пятая ценность при первом проходе сама открывает «Шаг 2» (автопереход)
            ps.onb["auto_advance"] = True
            if p.overselect:
                self.f.add("overselect_skipped", "шестую ценность нажать нельзя: после пятой экран уже сменился", p.user_id, self.clock.now)
        else:
            if p.overselect:
                extra = self.find(s, lambda t: not t.startswith("✓ ") and t in {VALUE_SHORT.get(x, x) for x in VALUES})
                if extra is not None:
                    r = await self.tap(ps, s, extra, "шестая ценность")
                    ps.onb["overselect_toast"] = r["toast"]
                    self.f.add("sixth_value", f"шестая ценность «{extra['text']}» → тост «{r['toast']}»", p.user_id, self.clock.now)
            s = self.screen(ps)
            btn = self.find(s, lambda t: t.startswith("Дальше"))
            if btn is None:
                self._stuck(ps, "values", "Дальше →")
                return "stuck"
            await self.tap(ps, s, btn)
        close("values")

        # ── Шаг 2 из 2: интересы ──
        st = self.screen(ps)
        if st is None or "Шаг 2 из 2" not in st.text:
            self._stuck(ps, "interests", "экран интересов")
            return "stuck"
        self._check_back(ps, "interests")
        await noise("interests")
        if wrong is not None:                                       # заметил ошибку: «← Назад», исправил, «Дальше»
            back = self.find(st, lambda t: t == "← Назад")
            ps.misclick_done = True
            ps.onb["misclick"] = {"step": "values", "wrong": wrong, "intended": p.top_values[-1], "recovery": "back"}
            if back is None:
                self.f.add("no_back_after_misclick", f"ошибся в ценностях (выбрал «{wrong}»), «← Назад» на экране интересов нет", p.user_id, self.clock.now)
                self._stuck(ps, "interests", "← Назад")
                return "stuck"
            await self.tap(ps, st, back, "исправить ценность")
            if not await pick(wrong) or not await pick(p.top_values[-1]):
                return "stuck"
            s = self.screen(ps)
            await self.tap(ps, s, self.find(s, lambda t: t.startswith("Дальше")), "после исправления")
            self.f.add("misclick_fixed_with_back", f"ошибся в ценностях и исправил через «← Назад» ({ps.taps - mark} нажатий)", p.user_id, self.clock.now)
            st = self.screen(ps)

        label_cat = {cat_label(c): c for c in ALL_CATS}

        def levels() -> dict[str, int]:
            s2 = self.screen(ps)
            out: dict[str, int] = {}
            for b in (s2.buttons() if s2 else []):
                m = re.match(r"^(✓✓ |✓ |— )?(.+)$", b["text"])
                c = label_cat.get(m.group(2)) if m else None
                if c:
                    out[c] = {"✓✓ ": 3, "✓ ": 2, "— ": 0}.get(m.group(1), 1)
            return out

        shown = levels()
        full = {c: shown.get(c, 1) for c in ALL_CATS}                # скрытые направления бот держит на уровне 1
        if "prefill" not in ps.onb:
            ps.onb["prefill"] = {"counts": dict(Counter(full.values())), "match": sum(1 for c in ALL_CATS if full[c] == p.interest_targets[c]),
                                 "total": len(ALL_CATS), "shown": len(shown), "shown_match": sum(1 for c, v in shown.items() if v == p.interest_targets[c])}
        # строка бюджета на «Шаге 2»: одно нажатие, экран не закрывается
        row_labels = {BUDGET_LABEL[a] for a in (1000, 2500, 0)}
        if self.find(st, lambda t: t.removeprefix("● ") in row_labels) is None:
            self.f.add("missing_button", "на «Шаге 2 из 2» нет строки бюджета", p.user_id, self.clock.now)
        elif p.budget_on_step:
            await self._budget_row(ps)
        left = p.max_interest_taps if p.abandon_step != "interests" else min(3, p.max_interest_taps)
        edits = 0
        # 1) убрать лишнее из восьми
        for c in [c for c in shown if p.interest_targets[c] == 0]:
            if left <= 0:
                break
            s = self.screen(ps)
            b = self.find(s, lambda t, c=c: re.sub(r"^(✓✓ |✓ |— )", "", t) == cat_label(c))
            if b is not None and levels().get(c, 1) > 0:
                await self.tap(ps, s, b, f"убрать {c}")
                left -= 1
                edits += 1
        # 2) добавить своё через «Все направления»
        want = [c for c in ALL_CATS if p.interest_targets[c] >= 2 and shown.get(c, 1) < 2]
        want.sort(key=lambda c: -p.interest_targets[c])
        on_all = False
        if want and left >= 2:
            s = self.screen(ps)
            b = self.find(s, lambda t: t.startswith("Все направления"))
            if b is None:
                self._stuck(ps, "interests", "Все направления")
                return "stuck"
            await self.tap(ps, s, b)
            left -= 1
            edits += 1
            on_all = True
            ps.onb["used_all_screen"] = True
            self._check_back(ps, "interests_all")
            brush = 2
            for c in want:
                if left <= 0:
                    break
                tgt = p.interest_targets[c]
                if tgt != brush:
                    s = self.screen(ps)
                    bb = self.find(s, lambda t, tgt=tgt: re.sub(r"^● ", "", t) == ("В первую очередь" if tgt == 3 else "Интересно"))
                    await self.tap(ps, s, bb, "кисть")
                    brush = tgt
                    left -= 1
                    edits += 1
                    if left <= 0:
                        break
                s = self.screen(ps)
                b = self.find(s, lambda t, c=c: re.sub(r"^(✓✓ |✓ |— )", "", t) == cat_label(c))
                if b is not None:
                    await self.tap(ps, s, b, f"добавить {c}")
                    left -= 1
                    edits += 1
        ps.onb["interest_edits"] = edits
        if p.abandon_step == "interests" and not ps.onb.get("abandon_used"):
            ps.onb["abandon_used"] = True
            close("interests")
            return self._abandon(ps, "interests", edits)
        s = self.screen(ps)
        btn = self.find(s, lambda t: t.startswith("Показать подборку"))
        if btn is None:
            self._stuck(ps, "interests", "Показать подборку →")
            return "stuck"
        saved_mid = s.mid
        await self.tap(ps, s, btn)
        close("interests")
        _ = on_all
        ps.onb["taps_total"] = ps.taps - ps.onb["taps_at_start"]
        if self.world.get(p.user_id, saved_mid).text.startswith("Профиль сохранён"):
            ps.status = "active"
            ps.onb["completed"] = self.clock.now.isoformat()
            ps.onboarded_t = self.clock.now
            return "completed"
        self.f.add("onboarding_not_saved", f"после «Показать подборку» экран не стал «Профиль сохранён»: {self.world.get(p.user_id, saved_mid).text[:60]!r}",
                   p.user_id, self.clock.now)
        ps.status = "abandoned"
        return "stuck"

    async def _budget_row(self, ps: PState) -> None:
        """Бюджет одним нажатием в строке «до 1 000 ₽ / до 2 500 ₽ / Не важно»; выбранное отмечается ●, экран остаётся."""
        p = ps.p
        want = BUDGET_LABEL[p.budget]
        mid0 = self.screen(ps).mid
        if p.misclick_step == "budget" and not ps.misclick_done:      # ошибся кнопкой, увидел ● не на той, нажал нужную
            wrong = BUDGET_LABEL[1000] if p.budget != 1000 else BUDGET_LABEL[2500]
            s = self.screen(ps)
            await self.tap(ps, s, self.find(s, lambda t, w=wrong: t.removeprefix("● ") == w), "ошибка в бюджете")
            ps.misclick_done = True
            ps.onb["misclick"] = {"step": "budget", "wrong": wrong, "intended": want, "recovery": "retap"}
            self.f.add("budget_row_fixed", f"ошибся кнопкой в строке бюджета («{wrong}»), увидел ● и нажал «{want}»", p.user_id, self.clock.now)
        s = self.screen(ps)
        b = self.find(s, lambda t: t.removeprefix("● ") == want)
        await self.tap(ps, s, b, "бюджет в строке «Шага 2»")
        s2 = self.screen(ps)
        marked = self.find(s2, lambda t: t == "● " + want) is not None
        stayed = s2 is not None and s2.mid == mid0 and "Шаг 2 из 2" in s2.text
        self.f.add("budget_row_ok" if marked and stayed else "budget_row_broken",
                   f"бюджет «{want}» в строке: ● {'есть' if marked else 'нет'}, экран {'остался' if stayed else 'сменился'}", p.user_id, self.clock.now)
        ps.onb["budget_set"] = "step"

    # ───────── «Уточнить под себя» ─────────
    def refine_needs(self, ps: PState) -> list[str]:
        p = ps.p
        ops = []
        if p.budget != 0 and not ps.onb.get("budget_set"):
            ops.append("budget")
        if p.aesthetics != default_aesthetics(p.top_values):
            ops.append("aesthetics")
        if sorted(p.times) != ["вечер", "день"]:
            ops.append("times")
        if p.company == "с детьми":
            ops.append("kids")
        return ops

    async def refine(self, ps: PState) -> bool:
        """Первая подборка → кнопка «Уточнить под себя» в её заголовке → меню. True, если пересобрал подборку."""
        p = ps.p
        ops = self.refine_needs(ps)
        first = next((r for r in ps.digests if r.origin == "first"), None)
        if (not ops and not p.help_at_notes) or first is None or ps.status != "active":
            return False
        head = self.world.get(p.user_id, first.header_mid)
        btn = self.find(head, lambda t: t.startswith("Уточнить"))
        if btn is None:
            self.f.add("missing_button", "в заголовке первой подборки нет «Уточнить под себя»", p.user_id, self.clock.now)
            return False
        t0 = ps.taps
        await self.tap(ps, head, btn)
        done: list[str] = []
        if p.help_at_notes and not ps.onb.get("help_used"):          # команда посреди меню «Уточнить» должна отработать как команда
            ps.onb["help_used"] = True
            h0 = len(self.world.chats[p.user_id])
            await self.say(ps, "/help")
            h = [m for m in self.world.chats[p.user_id][h0:] if not m.from_user]
            ok = bool(h) and "/digest" in h[0].text
            ps.onb["help_at_notes"] = ok
            self.f.add("command_in_notes_ok" if ok else "command_eaten_by_notes",
                       "в меню «Уточнить» /help " + ("отработал как команда" if ok else "не дал справки"), p.user_id, self.clock.now)
            if ops and self.find(self.screen(ps), lambda t: t.startswith("Бюджет")) is None:    # справка закрыла меню: открыть заново
                await self.tap(ps, head, btn)

        def menu() -> Stored | None:
            return self.screen(ps)

        async def open_item(prefix: str) -> Stored | None:
            m = menu()
            b = self.find(m, lambda t: t.startswith(prefix))
            if b is None:
                self.f.add("missing_button", f"в меню «Уточнить» нет пункта «{prefix}»", p.user_id, self.clock.now)
                return None
            await self.tap(ps, m, b)
            return self.screen(ps)

        for op in ops:
            if op == "budget":
                if p.misclick_step == "budget" and not ps.misclick_done:
                    ps.misclick_done = True
                    ps.onb["misclick"] = {"step": "budget", "wrong": "до 1 000 ₽", "intended": BUDGET_LABEL[p.budget], "recovery": "back"}
                    s = await open_item("Бюджет")
                    wrong_label = BUDGET_LABEL[0] if p.budget else BUDGET_LABEL[1000]
                    b = self.find(s, lambda t, wl=wrong_label: t.removeprefix("● ") == wl)
                    await self.tap(ps, s, b, "ошибка в бюджете")
                    self.f.add("misclick_fixed_with_back", "ошибся с бюджетом, меню показало выбранное, поправил повторным входом", p.user_id, self.clock.now)
                s = await open_item("Бюджет")
                b = self.find(s, lambda t: t.removeprefix("● ") == BUDGET_LABEL[p.budget]) if s else None
                if b is None:
                    return False
                await self.tap(ps, s, b)
                ps.onb["budget_set"] = "menu"
            elif op == "aesthetics":
                s = await open_item("Эстетика")
                want = "Да, важна" if p.aesthetics else "Не принципиально"
                b = self.find(s, lambda t, w=want: t.removeprefix("● ") == w) if s else None
                if b is None:
                    return False
                await self.tap(ps, s, b)
            elif op == "times":
                s = await open_item("Время")
                for t in SLOTS:
                    s = self.screen(ps)
                    b = self.find(s, lambda x, t=t: x.removeprefix("✓ ").lower() == t)
                    have = b is not None and b["text"].startswith("✓ ")
                    if b is not None and have != (t in p.times):
                        await self.tap(ps, s, b, f"время {t}")
                s = self.screen(ps)
                await self.tap(ps, s, self.find(s, lambda x: x == "Готово"))
            elif op == "kids":
                s = await open_item("С детьми")
                b = self.find(s, lambda t: t.removeprefix("● ").startswith("Да")) if s else None
                if b is None:
                    return False
                await self.tap(ps, s, b)
            done.append(op)
        rebuilt = False
        m = menu()
        b = self.find(m, lambda t: t.startswith("Пересобрать"))
        if b is not None:
            await self.tap(ps, m, b)
            rebuilt = True
        m = menu()
        b = self.find(m, lambda t: t == "Готово")
        if b is not None:
            await self.tap(ps, m, b)
        ps.onb["refine_ops"] = done
        ps.onb["refine_taps"] = ps.taps - t0
        ps.onb["refine_rebuilt"] = rebuilt
        return rebuilt

    async def reset_flow(self, ps: PState) -> str:
        """/reset у настроенного профиля: экран ценностей с прежним выбором → «Дальше» → «Сохранить»."""
        p = ps.p
        before = ps.taps
        await self.say(ps, "/reset")
        s = self.screen(ps)
        b = self.find(s, lambda t: t.startswith("Дальше"))
        if b is None:
            self._stuck(ps, "reset", "Дальше →")
            return "stuck"
        await self.tap(ps, s, b)
        s = self.screen(ps)
        b = self.find(s, lambda t: t.startswith(("Сохранить", "Показать подборку")))
        if b is None:
            self._stuck(ps, "reset", "Сохранить")
            return "stuck"
        ps.onb["reset_save_label"] = b["text"]
        await self.tap(ps, s, b)
        ps.onb["reset_taps"] = ps.taps - before
        _ = p
        return "completed"

    def _decide(self, ps: PState, f: float) -> str | None:
        """go | maybe | interest | skip | None по скрытой «подходит ли на самом деле» f."""
        p, rng = ps.p, ps.rng
        likes = rng.random() < sigmoid((f - 0.5) * 8)
        if likes:
            if rng.random() > p.decisive:
                return None
            wg, wm, wi = p.w_go_maybe_interest
            wg *= 0.6 + f
            x = rng.random() * (wg + wm + wi)
            return "go" if x < wg else "maybe" if x < wg + wm else "interest"
        return "skip" if rng.random() < p.decisive * 0.7 else None

    async def react_digest(self, ps: PState, rec: DigestRec) -> None:
        p, rng = ps.p, ps.rng
        if ps.status != "active" or not rec.cards:
            return
        first = rec.origin in ("first", "reset")
        p_open = 0.97 if first or rec.origin in ("manual", "rebuilt") else max(0.05, min(0.98, ps.E * p.p_open_scale))
        if rng.random() > p_open:
            ps.E *= 0.92
            return
        rec.opened = True
        lo, hi = p.view_range
        n_view = min(len(rec.cards), rng.randint(lo, hi))
        fits: list[float] = []
        for card in rec.cards[:n_view]:
            ev = self.events.get(card.event_id)
            if ev is None:
                continue
            f = p.fit(ev)
            fits.append(f)
            action = self._decide(ps, f)
            if action is None:
                continue
            await self._act_on_card(ps, rec, card, ev, action)
        if rec.go and rng.random() < 0.2:                    # «Мой план» под заголовком подборки
            head = self.world.get(p.user_id, rec.header_mid)
            b = self.find(head, lambda t: t == "Мой план")
            if b is not None:
                n0 = len(self.world.chats[p.user_id])
                res = await self.tap(ps, head, b, "кнопка «Мой план»")
                replies = [m for m in self.world.chats[p.user_id][n0:] if not m.from_user]
                self.commands.append({"t": self.clock.now.isoformat(), "u": p.user_id, "cmd": "/plan", "via": "button", "handled": res["handled"],
                                      "replies": [m.text[:160] for m in replies], "n": len(replies), "cycle": self.cycle_of(self.clock.now),
                                      "lines": len(replies[0].text.splitlines()) if replies else 0,
                                      "max_line": max((len(x) for x in replies[0].text.splitlines()), default=0) if replies else 0,
                                      "first_pre": False, "empty": bool(replies) and "пока ничего" in replies[0].text})
        if fits:
            s = sum(fits) / len(fits)
            coverage = min(1.0, len(rec.cards) / 5.0)       # меньше пяти карточек — подборка кажется скудной
            ps.E = max(0.0, min(1.0, 0.7 * ps.E + 0.3 * (0.1 + 0.95 * s * coverage)))

    def _set_decision(self, ps: PState, rec: DigestRec, card: CardRec, status: str, res: dict, reason: str | None = None) -> None:
        d = ps.decisions.get(card.event_id)
        fresh = d is None or d.get("status") != status
        if d is None or d.get("status") != status:
            redecided = d is not None and d.get("week") != rec.week
            d = {"status": status, "reason": reason, "week": rec.week, "card_day": card.day, "cycle": self.cycle_of(self.clock.now),
                 "redecided": bool(redecided or (d or {}).get("redecided"))}
            ps.decisions[card.event_id] = d
        else:
            d["reason"] = reason or d.get("reason")
            if reason is None:                     # то же решение повторно с другой карточки: день и неделя — с последней карточки
                d["card_day"], d["week"] = card.day, rec.week
        if reason is None:
            self.taps.append({"t": self.clock.now.isoformat(), "u": ps.p.user_id, "kind": "decision", "status": status,
                              "event_id": card.event_id, "week": rec.week, "cycle": self.cycle_of(self.clock.now),
                              "card_day": card.day, "toast": res["toast"], "origin": rec.origin, "taps": ps.taps})
        rec.decisions += 1
        if status == "иду":
            rec.go += 1
            local = self.clock.now.astimezone(ZoneInfo(ps.p.tz))
            if reason is None and self.on_same_day_go and card.day == local.date().isoformat() and local.hour >= 9:
                self.on_same_day_go(ps)
            if reason is None and fresh and self.on_going is not None:
                self.on_going(ps, card)
            if ps.first_go_taps is None:
                ps.first_go_taps = ps.taps
                ps.first_go_cycle = self.cycle_of(self.clock.now)

    async def _act_on_card(self, ps: PState, rec: DigestRec, card: CardRec, ev: dict, action: str, force_reason: str | None = None) -> None:
        p, rng = ps.p, ps.rng
        label = {"go": "Иду", "maybe": "Может быть", "interest": "Интересно", "skip": "Мимо"}[action]
        st = self.world.get(p.user_id, card.mid)
        # многодневное событие: иногда человек сначала выбирает другой день в ряду «Пт / Сб / Вс»
        days = [b for b in st.buttons() if str(b.get("callback_data", "")).startswith("y:")]
        if days and rng.random() < 0.25:
            other = [b for b in days if not b["text"].startswith("● ")]
            if other:
                pick = other[rng.randrange(len(other))]
                res0 = await self.tap(ps, st, pick, f"другой день {pick['text']}")
                fresh = parse_card(self.world.get(p.user_id, card.mid))
                if fresh is not None:
                    card.day, card.time_text, card.buttons = fresh.day, fresh.time_text, fresh.buttons
                prev = ps.decisions.get(card.event_id)
                if prev and prev.get("status") in ("иду", "может") and fresh is not None:
                    prev["card_day"] = fresh.day
                self.f.add("day_picked", f"на «{card.title[:30]}» выбрал день {pick['text']} → карточка показывает {card.day}, тост «{res0['toast']}»",
                           p.user_id, self.clock.now)
                self.taps.append({"t": self.clock.now.isoformat(), "u": p.user_id, "kind": "day_pick", "event_id": card.event_id,
                                  "week": rec.week, "cycle": self.cycle_of(self.clock.now), "day": card.day})
                st = self.world.get(p.user_id, card.mid)
        btn = self.find(st, lambda t, label=label: t.removeprefix("● ") == label)
        if btn is None and action == "interest":
            self.f.add("interest_button_missing", f"хотел нажать «Интересно» на «{card.title[:40]}», кнопки карточки: "
                       f"{[b['text'] for b in st.buttons()]}", p.user_id, self.clock.now)
            self.taps.append({"t": self.clock.now.isoformat(), "u": p.user_id, "kind": "wanted_interest", "event_id": card.event_id,
                              "week": rec.week, "cycle": self.cycle_of(self.clock.now)})
            return
        if btn is None:
            self.f.add("missing_button", f"карточка «{card.title[:40]}»: кнопки «{label}» нет", p.user_id, self.clock.now)
            return
        links_before = [b["text"] for b in st.buttons() if "url" in b]
        status = {"go": "иду", "maybe": "может", "interest": "интересно", "skip": "мимо"}[action]
        res = await self.tap(ps, st, btn, f"карточка «{card.title[:30]}»")
        st = self.world.get(p.user_id, card.mid)
        if res["exc"] is None and res["toast"] != ERROR_TOAST:
            self._set_decision(ps, rec, card, status, res)
        if p.double_tap > 0 and rng.random() < p.double_tap:
            r2 = await self.tap(ps, st, btn, "повторное нажатие (двойной тап)")
            if r2["toast"] == ERROR_TOAST:
                self.f.add("double_tap_error", f"двойной тап на «{label}» → тост «{r2['toast']}»; в логе: «message is not modified»",
                           p.user_id, self.clock.now)
            else:
                self.f.add("double_tap_ok", f"двойной тап на «{label}» → тост «{r2['toast']}», ошибки нет", p.user_id, self.clock.now)
        reason_chosen = False
        if action == "skip":
            st = self.world.get(p.user_id, card.mid)
            avail = {b["text"]: b for b in st.buttons() if str(b.get("callback_data", "")).startswith("r:")}
            if not avail:
                self.f.add("reasons_missing", "после «Мимо» нет кнопок причин", p.user_id, self.clock.now)
                return
            by_label = {lbl: name for name, lbl in REASON_LABEL.items()}
            reason = force_reason or (None if rng.random() < 0.15 else p.skip_reason(ev, rng, list(REASON_LABEL)))
            if reason is None:
                self.f.add("reason_not_answered", f"«Мимо» без выбора причины — блок причин остаётся в карточке «{card.title[:30]}»",
                           p.user_id, self.clock.now)
            else:
                want = REASON_LABEL[reason]
                if want not in avail:                           # причина спрятана за «Ещё…»
                    more = next((b for t, b in avail.items() if t.startswith("Ещё")), None)
                    if more is None:
                        self.f.add("reasons_missing", f"нет ни «{want}», ни «Ещё…»", p.user_id, self.clock.now)
                        return
                    await self.tap(ps, st, more, "ещё причины")
                    ps.onb["more_reasons_taps"] = ps.onb.get("more_reasons_taps", 0) + 1
                    st = self.world.get(p.user_id, card.mid)
                    avail = {b["text"]: b for b in st.buttons() if str(b.get("callback_data", "")).startswith("r:")}
                b2 = avail.get(want)
                if b2 is not None:
                    r3 = await self.tap(ps, st, b2, f"причина {want}")
                    reason_chosen = True
                    if r3["exc"] is None and r3["toast"] != ERROR_TOAST:
                        self._set_decision(ps, rec, card, "мимо", r3, reason=by_label[want])
                        if want == "Дорого":
                            await self._after_dear(ps, rec, card)
                        self.taps.append({"t": self.clock.now.isoformat(), "u": p.user_id, "kind": "reason", "reason": by_label[want],
                                          "event_id": card.event_id, "week": rec.week, "cycle": self.cycle_of(self.clock.now),
                                          "two_step": want not in ("Не моё", "Дорого", "Далеко", "Уже был")})
        st_after = self.world.get(p.user_id, card.mid)
        if action == "skip" and any(str(b.get("callback_data", "")).startswith("r:") for b in st_after.buttons()):
            ps.open_reasons = card.mid
        links_after = [b["text"] for b in st_after.buttons() if "url" in b]
        lost = [x for x in links_before if x not in links_after]
        if lost:
            is_last = card.mid == rec.cards[-1].mid
            self.f.add("links_lost_after_click", f"после «{label}»{' и выбора причины' if reason_chosen else ''} из карточки пропали "
                       f"{lost}{' (последняя карточка — вместе с «Весь дайджест»)' if is_last and 'Весь дайджест' in lost else ''}",
                       p.user_id, self.clock.now)

    async def nudge_probe(self, ps: PState, rec: DigestRec) -> bool:
        """Сценарий: человек с бюджетом «не важно» дважды подряд жмёт «Мимо — дорого» на разных карточках первой подборки."""
        cards = rec.cards[:2]
        if len(cards) < 2:
            return False
        for card in cards:
            await self._act_on_card(ps, rec, card, self.events.get(card.event_id) or {}, "skip", force_reason="дорого")
        return True

    async def _after_dear(self, ps: PState, rec: DigestRec, card: CardRec) -> None:
        """Второй раз «Мимо — дорого» при бюджете «не важно»: бот один раз подсказывает про «Уточнить под себя»."""
        p, rng = ps.p, ps.rng
        n = sum(1 for d in ps.decisions.values() if d.get("status") == "мимо" and d.get("reason") == "дорого")
        budget_free = not ps.onb.get("budget_set")
        due = n >= 2 and budget_free and not ps.onb.get("nudge_seen")
        last = next((m for m in reversed(self.world.chats[p.user_id]) if not m.from_user), None)
        shown = last is not None and last.text.startswith(NUDGE_START)
        if shown:
            ps.onb["nudge_seen"] = True
        if due:
            self.f.add("nudge_ok" if shown else "nudge_missing",
                       f"второе «Мимо — дорого» ({n}), бюджет «не важно»: подсказка " + ("пришла" if shown else "не пришла"), p.user_id, self.clock.now)
            if not shown:
                ps.onb["nudge_seen"] = True
        elif shown:
            self.f.add("nudge_unexpected", f"подсказка про бюджет пришла при {n} «дорого» и бюджете {'задан' if not budget_free else 'не важно'}", p.user_id, self.clock.now)
            return
        if not (shown and due):
            return
        btn = self.find(last, lambda t: t.startswith("Уточнить"))
        if btn is None:
            self.f.add("missing_button", "в подсказке про бюджет нет кнопки «Уточнить под себя»", p.user_id, self.clock.now)
            return
        if p.budget == 0 or rng.random() >= 0.55:
            return
        await self.tap(ps, last, btn, "из подсказки про бюджет")
        m = self.screen(ps)
        b = self.find(m, lambda t: t.startswith("Бюджет"))
        if b is None:
            self.f.add("missing_button", "в меню «Уточнить» из подсказки нет «Бюджет»", p.user_id, self.clock.now)
            return
        await self.tap(ps, m, b)
        m = self.screen(ps)
        b = self.find(m, lambda t: t.removeprefix("● ") == BUDGET_LABEL[p.budget])
        if b is not None:
            await self.tap(ps, m, b, "бюджет из подсказки")
            ps.onb["budget_set"] = "nudge"
            self.f.add("nudge_followed", f"из подсказки задал бюджет «{BUDGET_LABEL[p.budget]}»", p.user_id, self.clock.now)

    # ───────── оценки ─────────
    async def react_feedback(self, ps: PState, msgs: list[Stored]) -> None:
        p, rng = ps.p, ps.rng
        if ps.status != "active":
            return
        for st in msgs:
            b0 = next((b for b in st.buttons() if str(b.get("callback_data", "")).startswith("s:")), None)
            if b0 is None:
                continue
            eid = b0["callback_data"].split(":")[2]
            ev = self.events.get(eid)
            if ev is None:
                continue
            if rng.random() > p.p_rate:
                continue
            if rng.random() > p.p_attend:     # не дошёл — иногда нажимает «Не получилось пойти», оценку не ставит
                if rng.random() < 0.4:
                    skip = self.find(st, lambda t: t == "Не получилось пойти")
                    if skip is not None:
                        res = await self.tap(ps, st, skip, "не получилось пойти")
                        if res["exc"] is None and res["toast"] != ERROR_TOAST:
                            ps.decisions.setdefault(eid, {"reason": None, "week": None, "card_day": None})["status"] = "пропуск"
                            self.taps.append({"t": self.clock.now.isoformat(), "u": p.user_id, "kind": "decision", "status": "пропуск",
                                              "event_id": eid, "week": None, "cycle": self.cycle_of(self.clock.now), "card_day": None,
                                              "toast": res["toast"], "origin": "feedback", "taps": ps.taps})
                continue
            f = p.fit(ev)
            rating = int(max(1, min(5, round(1 + 4 * f + p.rating_bias + rng.gauss(0.05, 0.9)))))
            btn = self.find(st, lambda t, r=rating: t.removeprefix("● ") == f"{r} ★")
            if btn is None:
                self.f.add("missing_button", f"оценка: кнопки {rating} ★ нет", p.user_id, self.clock.now)
                continue
            n_chat = len(self.world.chats[p.user_id])
            res = await self.tap(ps, st, btn, f"оценка {rating}")
            ok = res["exc"] is None and res["toast"] != ERROR_TOAST
            if ok and self.on_rated is not None:
                self.on_rated(ps, rating, list(self.world.chats[p.user_id][n_chat:]))
            if ok:
                ps.ratings.append({"event_id": eid, "rating": rating})
                ps.decisions.setdefault(eid, {"status": "иду", "reason": None, "week": None, "card_day": None})["rating"] = rating
                self.taps.append({"t": self.clock.now.isoformat(), "u": p.user_id, "kind": "rating", "rating": rating, "event_id": eid,
                                  "cycle": self.cycle_of(self.clock.now), "toast": res["toast"]})
            ps.E = max(0.0, min(1.0, ps.E + (0.05 if rating >= 4 else -0.06 if rating <= 2 else 0.0)))

    # ───────── команды ─────────
    async def run_cmd(self, ps: PState, cmd: str) -> list[Stored]:
        p = ps.p
        before = len(self.world.chats[p.user_id])
        res = await self.say(ps, cmd)
        replies = [m for m in self.world.chats[p.user_id][before:] if not m.from_user]
        lines = [ln for m in replies[:1] for ln in m.text.splitlines()]
        self.commands.append({"t": self.clock.now.isoformat(), "u": p.user_id, "cmd": cmd, "handled": res["handled"],
                              "replies": [m.text[:160] for m in replies], "n": len(replies), "cycle": self.cycle_of(self.clock.now),
                              "lines": len(lines), "max_line": max((len(x) for x in lines), default=0),
                              "first_pre": bool(replies) and replies[0].html.startswith("<pre>")})
        if not replies:
            self.f.add("command_silent", f"{cmd} без ответа бота (handled={res['handled']})", p.user_id, self.clock.now)
        return replies

    async def delete_flow(self, ps: PState) -> bool:
        p = ps.p
        replies = await self.run_cmd(ps, "/delete")
        st = replies[-1] if replies else None
        btn = self.find(st, lambda t: t.startswith("Удалить"))
        if btn is None:
            self.f.add("missing_button", "/delete: нет кнопки подтверждения", p.user_id, self.clock.now)
            return False
        await self.tap(ps, st, btn)
        ps.status = "deleted"
        return True
