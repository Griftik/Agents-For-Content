"""Состояние человека в приложении: аккаунт с одним или несколькими профилями (у каждого свои решения и своя история)."""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from ..personas import Persona


@dataclass
class ProfileState:
    pid: int
    kind: str                          # self | parent | child | other
    p: Persona                         # скрытый вкус именно этого профиля
    name: str = ""                     # имя профиля в приложении («я» — имя человека; «Мама», «Ребёнок»)
    decisions: dict = field(default_factory=dict)    # event_id → {status, reason, day, rating, via_invite}
    ratings: list = field(default_factory=list)
    onb: dict = field(default_factory=dict)          # completed, taps_total, steps, prefill, interest_edits, ...
    learn: dict = field(default_factory=dict)        # записи проб обучения


@dataclass
class AppUser:
    p: Persona                         # владелец аккаунта (профиль «я»)
    rng: random.Random
    E: float
    uid: int | None = None             # user_id аккаунта, выданный POST /api/session
    token: str | None = None
    status: str = "new"                # new | guest | onboarding | abandoned | active | churned | deleted
    taps: int = 0                      # действия человека в интерфейсе с открытия ссылки
    onb: dict = field(default_factory=dict)          # онбординг аккаунта (профиль «я»)
    profiles: list[ProfileState] = field(default_factory=list)
    cur: int = 0                       # индекс активного профиля (переключатель в шапке)
    second: Persona | None = None      # вкус второго профиля (у ~20 % персон: ребёнок или родитель), создаётся позже
    opens: list[dict] = field(default_factory=list)  # записи открытий приложения
    active_cycles: set = field(default_factory=set)  # недели, в которые открывал приложение
    decision_cycles: set = field(default_factory=set)
    churn_cycle: int | None = None
    first_go_taps: int | None = None
    onboarded_t: object = None

    @property
    def prof(self) -> ProfileState:
        return self.profiles[self.cur]

    @property
    def decisions(self) -> dict:                       # решения активного профиля (для общих хелперов)
        return self.prof.decisions
