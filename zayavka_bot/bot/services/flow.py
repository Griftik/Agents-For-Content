"""Порядок вопросов заявки: вперёд, назад, ветка консультанта."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from bot.content import Content

# Этапы в users.stage
STAGE_WELCOME = "welcome"
STAGE_CONTACT = "contact"
STAGE_COMPANY = "company"
STAGE_DONE = "done"
STAGE_TRAINING = "specialist_training"
Q_PREFIX = "q:"


def q_stage(code: str) -> str:
    return Q_PREFIX + code


def stage_question(stage: str | None) -> str | None:
    if stage and stage.startswith(Q_PREFIX):
        return stage[len(Q_PREFIX):]
    return None


@dataclass
class Next:
    """Куда идти после ответа: следующий вопрос, либо конец заявки / ветки."""
    question: str | None = None
    finished: bool = False     # 11 вопросов пройдены → тизер и контакт
    specialist: bool = False   # ветка консультанта пройдена → документы


def next_step(c: Content, q_code: str, a_code: str) -> Next:
    if q_code == c.specialist_need.code:
        return Next(specialist=True)
    q = c.question(q_code)
    if q is None:
        raise KeyError(q_code)
    target = q.branch.get(a_code)
    if target:
        return Next(question=target)
    order = c.order
    i = order.index(q_code)
    if i + 1 < len(order):
        return Next(question=order[i + 1])
    return Next(finished=True)


def prev_question(c: Content, q_code: str, answers: Mapping[str, str]) -> str | None:
    """Вопрос, на который ведёт «Назад». None — назад некуда (первый вопрос)."""
    if q_code == c.specialist_need.code:
        # в ветку попадают из вопроса, у которого есть branch
        for q in c.questions:
            if c.specialist_need.code in q.branch.values():
                return q.code
        return c.order[0]
    order = c.order
    i = order.index(q_code)
    return order[i - 1] if i > 0 else None


def question_number(c: Content, q_code: str) -> int:
    """Номер для «Вопрос N из 11». Ветка консультанта идёт вторым вопросом."""
    if q_code == c.specialist_need.code:
        return 2
    return c.order.index(q_code) + 1
