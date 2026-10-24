"""Поведение виртуальных людей: онбординг, реакция на дайджест, оценки, команды.

Все действия — только через Dispatcher.feed_update. Кнопки берутся из клавиатуры последнего сообщения бота
(или конкретной карточки): человек читает подписи, а не знает callback_data. Исключение — event_id в служебных
записях для сверки с БД, он никогда не подставляется в нажатие.
"""
from __future__ import annotations

import random
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from aiogram import Bot
from aiogram.dispatcher.event.bases import UNHANDLED

from leisure.core.catalog import ALL_CATS, SLOTS, VALUES
from leisure.core.timeutil import MONTHS

from .fakebot import FakeTelegram, Stored
from .personas import STEPS, Persona, sigmoid

BUDGET_LABEL = {0: "Без ограничения", 1000: "до 1 000 ₽", 2500: "до 2 500 ₽", 5000: "до 5 000 ₽"}
AREA_LABEL = {"центр": "Центр", "любой": "Любой район", "свой округ": "Свой округ"}
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

    def add(self, code: str, msg: str, uid: int | None = None, t: datetime | None = None, n: int = 1) -> None:
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
    return CardRec(st.mid, btn["callback_data"].split(":", 2)[2], lines[0], day, in_weekend, time_text,
                   [b["text"] for b in st.buttons()])


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

    # ───────── базовые операции ─────────
    def _log(self, ps: PState, kind: str, **kw: Any) -> None:
        self.log.append({"t": self.clock.now.isoformat(), "u": ps.p.user_id, "k": kind, **kw})

    async def _feed(self, ps: PState, upd, cb_id: str | None, what: str) -> dict:
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
        res = await self._feed(ps, upd, cb_id, f"нажатие «{btn['text']}» ({cb_short(btn['callback_data'])}) {why}".strip())
        return res

    def screen(self, ps: PState) -> Stored | None:
        return self.world.last_bot_message(ps.p.user_id)

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
        """Полный проход онбординга. Возвращает completed | abandoned | stuck."""
        p = ps.p
        if ps.status != "onboarding":
            ps.status = "onboarding"
        ps.onb.setdefault("started", self.clock.now.isoformat())
        ps.onb.setdefault("taps_at_start", ps.taps)
        ps.onb.setdefault("redo", 0)
        steps_taps: dict[str, int] = ps.onb.setdefault("steps", {})
        mark = ps.taps
        cur = {"step": "consent"}

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

        await self.say(ps, command)
        st = self.screen(ps)
        if st is None or not st.buttons():
            self._stuck(ps, "consent", "ответ на " + command)
            return "stuck"
        self._check_back(ps, "consent")
        if p.abandon_step == "consent" and not ps.onb.get("abandon_used"):
            ps.onb["abandon_used"] = True
            close("consent")
            return self._abandon(ps, "consent")
        btn = self.find(st, lambda t: t.startswith("Согласен"))
        if btn is None:
            self._stuck(ps, "consent", "Согласен, поехали")
            return "stuck"
        await self.tap(ps, st, btn)
        close("consent")

        # ── 1. ценности ──
        cur["step"] = "values"
        st = self.screen(ps)
        self._check_back(ps, "values")
        await noise("values")
        for i, v in enumerate(p.top_values):
            if p.abandon_step == "values" and i == p.abandon_sub and not ps.onb.get("abandon_used"):
                ps.onb["abandon_used"] = True
                close("values")
                return self._abandon(ps, "values", i)
            st = self.screen(ps)
            btn = self.find(st, lambda t, v=v: t.removeprefix("✓ ") == v)
            if btn is None:
                self._stuck(ps, "values", v)
                return "stuck"
            await self.tap(ps, st, btn, f"ценность {v}")
        if p.overselect:
            st = self.screen(ps)
            extra = self.find(st, lambda t: t.removeprefix("✓ ") in VALUES and not t.startswith("✓ "))
            if extra is not None:
                r = await self.tap(ps, st, extra, "шестая ценность")
                ps.onb["overselect_toast"] = r["toast"]
                self.f.add("sixth_value", f"шестая ценность «{extra['text']}» → тост «{r['toast']}»", p.user_id, self.clock.now)
        st = self.screen(ps)
        btn = self.find(st, lambda t: t.startswith("Дальше"))
        if btn is None:
            self._stuck(ps, "values", "Дальше →")
            return "stuck"
        await self.tap(ps, st, btn)
        close("values")

        # ── 2. остальные ценности: важно / не очень ──
        cur["step"] = "weights"
        k = 0
        while True:
            st = self.screen(ps)
            if st is None or "насколько важно" not in st.text:
                break
            if k == 0:
                self._check_back(ps, "weights")
                await noise("weights")
            if p.abandon_step == "weights" and k == p.abandon_sub and not ps.onb.get("abandon_used"):
                ps.onb["abandon_used"] = True
                close("weights")
                return self._abandon(ps, "weights", k)
            m = re.search(r"«(.+?)»", st.text)
            val = m.group(1) if m else ""
            want = "Важно" if val in p.important else "Не очень"
            btn = self.find(st, lambda t, w=want: t == w)
            if btn is None:
                self._stuck(ps, "weights", want)
                return "stuck"
            await self.tap(ps, st, btn, f"«{val}» {want}")
            k += 1
            if k > 20:
                break
        ps.onb["weight_prompts"] = k
        close("weights")

        # ── 3. интересы ──
        cur["step"] = "interests"
        st = self.screen(ps)
        if st is None or "Интересы" not in st.text:
            self._stuck(ps, "interests", "экран интересов")
            return "stuck"
        self._check_back(ps, "interests")
        ps.onb["interest_buttons"] = len([b for b in st.buttons() if "·" in b["text"]])
        ps.onb["interest_rows"] = len(st.rows or [])
        await noise("interests")

        def levels() -> dict[str, int]:
            s = self.screen(ps)
            out = {}
            for b in (s.buttons() if s else []):
                m = re.match(r"(.+?) · (.+)$", b["text"])
                if m and m.group(1) in ALL_CATS:
                    out[m.group(1)] = LEVEL_OF_LABEL.get(m.group(2), -1)
            return out

        if "prefill" not in ps.onb:       # что бот предзаполнил до правок человека
            pre = levels()
            ps.onb["prefill"] = {"counts": dict(Counter(pre.values())), "match": sum(1 for c, v in pre.items() if v == p.interest_targets[c]),
                                 "total": len(pre)}

        taps_left = p.max_interest_taps if not (p.abandon_step == "interests") else min(3, p.max_interest_taps)
        order = ([c for c in ALL_CATS if p.interest_targets[c] == 3] + [c for c in ALL_CATS if p.interest_targets[c] == 0]
                 + [c for c in ALL_CATS if p.interest_targets[c] == 2])
        edits = 0
        for c in order:
            while taps_left > 0:
                cur_lv = levels().get(c, -1)
                tgt = p.interest_targets[c]
                if cur_lv == tgt or cur_lv < 0:
                    break
                st = self.screen(ps)
                btn = self.find(st, lambda t, c=c: t.startswith(c + " · "))
                await self.tap(ps, st, btn, f"интерес {c}")
                taps_left -= 1
                edits += 1
        ps.onb["interest_edits"] = edits
        if p.abandon_step == "interests" and not ps.onb.get("abandon_used"):
            ps.onb["abandon_used"] = True
            close("interests")
            return self._abandon(ps, "interests", edits)
        st = self.screen(ps)
        btn = self.find(st, lambda t: t.startswith("Готово"))
        if btn is None:
            self._stuck(ps, "interests", "Готово →")
            return "stuck"
        await self.tap(ps, st, btn)
        close("interests")

        # ── 4. параметры ──
        async def single(step: str, texts: list[str], intended: str, wrong: str | None) -> str | None:
            """Один выбор из списка кнопок. wrong — подпись, которую человек нажмёт по ошибке (misclick)."""
            if p.abandon_step == step and not ps.onb.get("abandon_used"):
                ps.onb["abandon_used"] = True
                close(step)
                return self._abandon(ps, step)
            await noise(step)
            self._check_back(ps, step)
            st = self.screen(ps)
            mis = p.misclick_step == step and not ps.misclick_done and wrong is not None
            label = wrong if mis else intended
            btn = self.find(st, lambda t: t.removeprefix("✓ ") == label)
            if btn is None:
                self._stuck(ps, step, label)
                return "stuck"
            await self.tap(ps, st, btn, f"{step}: {label}")
            close(step)
            if mis:
                ps.misclick_done = True
                has_back = self._check_back(ps, step + "_after_misclick")
                self.f.add("no_back_after_misclick", f"выбрал «{label}» вместо «{intended}» на шаге «{step}»; кнопка «Назад»: "
                           f"{'есть' if has_back else 'нет'}; кнопки: {[b['text'] for b in self.screen(ps).buttons()][:5]}",
                           p.user_id, self.clock.now)
                ps.onb["misclick"] = {"step": step, "wrong": label, "intended": intended, "recovery": p.misclick_recovery}
                if p.misclick_recovery == "reset":
                    return "restart"
            return None

        cur["step"] = "company"
        wrong_company = next(c for c in ["один", "с партнёром", "с друзьями", "с детьми", "любая"] if c != p.company)
        r = await single("company", [], p.company, wrong_company)
        if r:
            return await self._finish_flow(ps, r)
        cur["step"] = "times"
        if p.abandon_step == "times" and not ps.onb.get("abandon_used"):
            ps.onb["abandon_used"] = True
            close("times")
            return self._abandon(ps, "times")
        await noise("times")
        self._check_back(ps, "times")
        for t in p.times:
            st = self.screen(ps)
            btn = self.find(st, lambda x, t=t: x.removeprefix("✓ ") == t)
            if btn is None:
                self._stuck(ps, "times", t)
                return "stuck"
            await self.tap(ps, st, btn, f"время {t}")
        st = self.screen(ps)
        btn = self.find(st, lambda t: t.startswith("Дальше"))
        if btn is None:
            self._stuck(ps, "times", "Дальше →")
            return "stuck"
        await self.tap(ps, st, btn)
        close("times")
        cur["step"] = "budget"
        wrong_budget = BUDGET_LABEL[0] if p.budget else BUDGET_LABEL[1000]
        r = await single("budget", [], BUDGET_LABEL[p.budget], wrong_budget)
        if r:
            return await self._finish_flow(ps, r)
        cur["step"] = "aesthetics"
        r = await single("aesthetics", [], "Да, важна" if p.aesthetics else "Не принципиально",
                         "Не принципиально" if p.aesthetics else "Да, важна")
        if r:
            return await self._finish_flow(ps, r)
        cur["step"] = "areas"
        wrong_area = next(a for a in ("центр", "любой", "свой округ") if a != p.area)
        r = await single("areas", [], AREA_LABEL[p.area], AREA_LABEL[wrong_area])
        if r:
            return await self._finish_flow(ps, r)

        # ── 5. заметка ──
        cur["step"] = "notes"
        if p.abandon_step == "notes" and not ps.onb.get("abandon_used"):
            ps.onb["abandon_used"] = True
            close("notes")
            return self._abandon(ps, "notes")
        self._check_back(ps, "notes")
        before = len(self.world.chats[p.user_id])
        if p.help_at_notes:
            await self.say(ps, "/help")
            ps.onb["help_at_notes"] = True
            self.f.add("command_eaten_by_notes", "на шаге заметки отправил /help — бот принял команду за текст заметки и завершил онбординг",
                       p.user_id, self.clock.now)
        elif p.note:
            await self.say(ps, p.note)
        else:
            st = self.screen(ps)
            btn = self.find(st, lambda t: t.startswith("Пропустить"))
            if btn is None:
                self._stuck(ps, "notes", "Пропустить")
                return "stuck"
            await self.tap(ps, st, btn)
        close("notes")
        replies = [m for m in self.world.chats[p.user_id][before:] if not m.from_user]
        ps.onb["taps_total"] = ps.taps - ps.onb["taps_at_start"]
        if any("Профиль сохранён" in m.text for m in replies):
            ps.status = "active"
            ps.onb["completed"] = self.clock.now.isoformat()
            ps.onboarded_t = self.clock.now
            return "completed"
        self.f.add("onboarding_not_saved", f"после последнего шага нет «Профиль сохранён»: {[m.text[:60] for m in replies][:2]}",
                   p.user_id, self.clock.now)
        ps.status = "abandoned"
        return "stuck"

    async def _finish_flow(self, ps: PState, r: str) -> str:
        """Обработка результата шага: restart → /reset и заново (повторный проход без новых промахов)."""
        if r == "restart":
            ps.onb["redo"] = ps.onb.get("redo", 0) + 1
            res = await self.onboard(ps, "/reset")
            return res
        return r

    # ───────── реакция на дайджест ─────────
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
        p_open = 0.97 if first or rec.origin == "manual" else max(0.05, min(0.98, ps.E * p.p_open_scale))
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
        if fits:
            s = sum(fits) / len(fits)
            coverage = min(1.0, len(rec.cards) / 5.0)       # меньше пяти карточек — подборка кажется скудной
            ps.E = max(0.0, min(1.0, 0.7 * ps.E + 0.3 * (0.1 + 0.95 * s * coverage)))

    def _set_decision(self, ps: PState, rec: DigestRec, card: CardRec, status: str, res: dict, reason: str | None = None) -> None:
        d = ps.decisions.get(card.event_id)
        if d is None or d.get("status") != status:
            redecided = d is not None and d.get("week") != rec.week
            d = {"status": status, "reason": reason, "week": rec.week, "card_day": card.day, "cycle": self.cycle_of(self.clock.now),
                 "redecided": bool(redecided or (d or {}).get("redecided"))}
            ps.decisions[card.event_id] = d
        else:
            d["reason"] = reason or d.get("reason")
        if reason is None:
            self.taps.append({"t": self.clock.now.isoformat(), "u": ps.p.user_id, "kind": "decision", "status": status,
                              "event_id": card.event_id, "week": rec.week, "cycle": self.cycle_of(self.clock.now),
                              "card_day": card.day, "toast": res["toast"], "origin": rec.origin, "taps": ps.taps})
        rec.decisions += 1
        if status == "иду":
            rec.go += 1
            if ps.first_go_taps is None:
                ps.first_go_taps = ps.taps
                ps.first_go_cycle = self.cycle_of(self.clock.now)

    async def _act_on_card(self, ps: PState, rec: DigestRec, card: CardRec, ev: dict, action: str) -> None:
        p, rng = ps.p, ps.rng
        label = {"go": "Иду", "maybe": "Может быть", "interest": "Интересно", "skip": "Мимо"}[action]
        st = self.world.get(p.user_id, card.mid)
        btn = self.find(st, lambda t, label=label: t.removeprefix("● ") == label)
        if btn is None and action == "interest":
            self.f.add("interest_button_missing", f"хотел нажать «Интересно» на «{card.title[:40]}», кнопки карточки: "
                       f"{[b['text'] for b in st.buttons()]}", p.user_id, self.clock.now)
            self.taps.append({"t": self.clock.now.isoformat(), "u": p.user_id, "kind": "wanted_interest", "event_id": card.event_id,
                              "week": rec.week, "cycle": self.cycle_of(self.clock.now)})
            if rng.random() < 0.5:
                action, label = "maybe", "Может быть"
                btn = self.find(st, lambda t: t.removeprefix("● ") == "Может быть")
            else:
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
        reason_chosen = False
        if action == "skip":
            st = self.world.get(p.user_id, card.mid)
            avail = [b["text"] for b in st.buttons() if str(b.get("callback_data", "")).startswith("r:")]
            if not avail:
                self.f.add("reasons_missing", "после «Мимо» нет кнопок причин", p.user_id, self.clock.now)
                return
            if rng.random() < 0.15:
                self.f.add("reason_not_answered", f"«Мимо» без выбора причины — кнопки причин остаются в карточке «{card.title[:30]}»",
                           p.user_id, self.clock.now)
            else:
                reason = p.skip_reason(ev, rng, avail)
                want = reason if reason else "Без причины"
                b2 = self.find(st, lambda t: t == want)
                r3 = await self.tap(ps, st, b2, f"причина {want}")
                reason_chosen = True
                if r3["exc"] is None and r3["toast"] != ERROR_TOAST:
                    self._set_decision(ps, rec, card, "мимо", r3, reason=reason or "")
                    self.taps.append({"t": self.clock.now.isoformat(), "u": p.user_id, "kind": "reason", "reason": reason or "",
                                      "event_id": card.event_id, "week": rec.week, "cycle": self.cycle_of(self.clock.now)})
        st_after = self.world.get(p.user_id, card.mid)
        links_after = [b["text"] for b in st_after.buttons() if "url" in b]
        lost = [x for x in links_before if x not in links_after]
        if lost:
            is_last = card.mid == rec.cards[-1].mid
            self.f.add("links_lost_after_click", f"после «{label}»{' и выбора причины' if reason_chosen else ''} из карточки пропали "
                       f"{lost}{' (последняя карточка — вместе с «Весь дайджест»)' if is_last and 'Весь дайджест' in lost else ''}",
                       p.user_id, self.clock.now)

    # ───────── оценки ─────────
    async def react_feedback(self, ps: PState, msgs: list[Stored]) -> None:
        p, rng = ps.p, ps.rng
        if ps.status != "active":
            return
        for st in msgs:
            b0 = next((b for b in st.buttons() if str(b.get("callback_data", "")).startswith("s:")), None)
            if b0 is None:
                continue
            eid = b0["callback_data"].split(":", 2)[2]
            ev = self.events.get(eid)
            if ev is None:
                continue
            if rng.random() > p.p_rate:
                continue
            if rng.random() > p.p_attend:     # не дошёл — не оценивает
                continue
            f = p.fit(ev)
            rating = int(max(1, min(5, round(1 + 4 * f + p.rating_bias + rng.gauss(0.05, 0.9)))))
            btn = self.find(st, lambda t, r=rating: t == "★" * r)
            if btn is None:
                self.f.add("missing_button", f"оценка: кнопки {'★' * rating} нет", p.user_id, self.clock.now)
                continue
            res = await self.tap(ps, st, btn, f"оценка {rating}")
            ok = res["exc"] is None and res["toast"] != ERROR_TOAST
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
        btn = self.find(st, lambda t: t.startswith("Да, удалить"))
        if btn is None:
            self.f.add("missing_button", "/delete: нет кнопки подтверждения", p.user_id, self.clock.now)
            return False
        await self.tap(ps, st, btn)
        ps.status = "deleted"
        return True
