"""11 вопросов заявки: ответ, «Назад», «Пропустить», ветка консультанта (п. 3.3)."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message

from bot.content import get_content
from bot.db import repo
from bot.services import flow, leadflow

router = Router(name="application")


def _msg(cb: CallbackQuery) -> Message | None:
    return cb.message if isinstance(cb.message, Message) else None


@router.callback_query(F.data.startswith("a:"))
async def cb_answer(cb: CallbackQuery, bot: Bot) -> None:
    c = get_content()
    _, q_code, a_code = (cb.data or "").split(":", 2)
    u = await repo.get_user(cb.from_user.id)
    current = flow.stage_question(u.stage if u else None)
    q = c.question(q_code)
    if u is None or q_code != current or q is None:
        # кнопка из старого сообщения — не ломаем порядок, молча игнорируем
        await cb.answer()
        return
    if q.label(a_code) is None and not (q.skippable and a_code == "skip"):
        await cb.answer()
        return
    await cb.answer()

    await repo.save_answer(u.id, q_code, a_code)
    await repo.log_event(u.id, "q_answered", q_code=q_code)
    if q.branch and q.branch.get(a_code) != c.specialist_need.code:
        await repo.delete_answers(u.id, [c.specialist_need.code])  # передумал быть консультантом

    nxt = flow.next_step(c, q_code, a_code)
    msg = _msg(cb)
    if nxt.question:
        await leadflow.show_question(bot, u.id, nxt.question, edit=msg)
        return
    # конец заявки или ветки: оставляем последний вопрос с выбранным ответом, без кнопок
    if msg:
        try:
            await msg.edit_text(f"{msg.text}\n\n→ {q.label(a_code) or a_code}", reply_markup=None)
        except Exception:  # noqa: BLE001
            pass
    if nxt.specialist:
        await leadflow.run_specialist(bot, u.id)
    elif nxt.finished:
        await leadflow.finish_questions(bot, u.id)


@router.callback_query(F.data.startswith("back:"))
async def cb_back(cb: CallbackQuery, bot: Bot) -> None:
    c = get_content()
    await cb.answer()
    q_code = (cb.data or "").split(":", 1)[1]
    u = await repo.get_user(cb.from_user.id)
    if u is None or flow.stage_question(u.stage) != q_code:
        return
    answers = await repo.get_answers(u.id)
    prev = flow.prev_question(c, q_code, answers)
    if prev:
        await leadflow.show_question(bot, u.id, prev, edit=_msg(cb))
