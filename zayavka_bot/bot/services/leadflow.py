"""Шаги сценария, общие для хендлеров и планировщика: вопросы, тизер, контакт, финал заявки,
ветка специалиста, доставка разбора, карточка админу."""
from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile, Message, ReplyKeyboardRemove

from bot.config import get_settings
from bot.content import get_content
from bot.db import repo
from bot.db.models import utcnow
from bot.keyboards import kb
from bot.services import crm, flow, insights, mapping, notify, scoring
from bot.services.cards import admin_card, pain_text

log = logging.getLogger(__name__)

HOT_REMINDERS = ["hot_reminder_24h", "hot_reminder_72h"]
_video_note_id: str | None = None


# --- приветствие ------------------------------------------------------------
async def send_welcome(bot: Bot, chat_id: int) -> None:
    """Кружок первым (если файл есть), текст вторым (п. 3.2)."""
    global _video_note_id
    c = get_content()
    path = Path(str(c.texts.get("welcome_video_note") or "content/media/welcome.mp4"))
    if not path.is_absolute():
        path = get_settings().content_dir.parent / path
    if _video_note_id or path.exists():
        try:
            msg = await bot.send_video_note(chat_id, _video_note_id or FSInputFile(path))
            if msg.video_note:
                _video_note_id = msg.video_note.file_id
        except TelegramBadRequest as e:
            log.warning("кружок не отправлен: %s", e)
    await bot.send_message(chat_id, c.t("welcome"), reply_markup=kb.start(c))


# --- вопросы ----------------------------------------------------------------
def question_text(q_code: str) -> str:
    c = get_content()
    q = c.question(q_code)
    assert q is not None
    if q_code == c.specialist_need.code:
        return q.text
    return f"{c.t('progress', n=flow.question_number(c, q_code))}\n\n{q.text}"


def question_markup(q_code: str):
    c = get_content()
    q = c.question(q_code)
    assert q is not None
    return kb.question(c, q, with_back=flow.question_number(c, q_code) > 1)


async def show_question(bot: Bot, user_id: int, q_code: str, edit: Message | None = None) -> None:
    await repo.set_stage(user_id, flow.q_stage(q_code))
    text, markup = question_text(q_code), question_markup(q_code)
    if edit is not None:
        try:
            await edit.edit_text(text, reply_markup=markup)
            return
        except TelegramBadRequest:
            pass  # сообщение слишком старое или не изменилось — шлём новое
    await bot.send_message(user_id, text, reply_markup=markup)


# --- после 11-го вопроса: тизер и контакт -----------------------------------
async def finish_questions(bot: Bot, user_id: int) -> None:
    c = get_content()
    answers = await repo.get_answers(user_id)
    await repo.log_event(user_id, "app_completed")
    first, second = insights.pick(answers, c.insights)
    await bot.send_message(user_id, f"{c.t('teaser_intro')}\n\n{first}\n\n{second}")
    await ask_contact(bot, user_id, with_later=True)
    await repo.set_stage(user_id, flow.STAGE_CONTACT)
    await repo.cancel_jobs(user_id, ["contact_timeout"])
    await repo.schedule(user_id, "contact_timeout", timedelta(minutes=get_settings().contact_timeout_min))


async def ask_contact(bot: Bot, user_id: int, with_later: bool) -> None:
    c = get_content()
    privacy = get_settings().privacy_url or "TODO(Евгений): PRIVACY_URL"
    text = f"{c.t('ask_contact')}\n\n{c.t('consent_line', privacy_url=privacy)}"
    await bot.send_message(user_id, text, reply_markup=kb.contact(c, with_later), disable_web_page_preview=True)


async def remove_reply_keyboard(bot: Bot, chat_id: int) -> None:
    """Убрать reply-клавиатуру без лишнего сообщения в чате: отправить и сразу удалить."""
    try:
        m = await bot.send_message(chat_id, "…", reply_markup=ReplyKeyboardRemove())
        await bot.delete_message(chat_id, m.message_id)
    except TelegramBadRequest:
        pass


async def ask_company(bot: Bot, user_id: int) -> None:
    c = get_content()
    await remove_reply_keyboard(bot, user_id)
    await repo.set_stage(user_id, flow.STAGE_COMPANY)
    await bot.send_message(user_id, c.company_text or c.t("ask_company"), reply_markup=kb.company_skip(c))


async def save_contact(bot: Bot, user_id: int, phone: str) -> None:
    """Нажатие кнопки = согласие (п. 3.4): consent_at фиксируем вместе с телефоном."""
    await repo.update_lead(user_id, phone=phone, consent_at=utcnow())
    await repo.log_event(user_id, "contact_shared")
    crm.push(user_id)


# --- финал заявки -----------------------------------------------------------
async def finalize(bot: Bot, user_id: int) -> None:
    """Сегмент, тип сессии, карточка админу, CRM, маршрут по сегменту (п. 3.6)."""
    c = get_content()
    u = await repo.get_user(user_id)
    if u is None or u.stage == flow.STAGE_DONE:
        return
    await repo.cancel_jobs(user_id, ["contact_timeout"])
    answers = await repo.get_answers(user_id)
    seg, sc = scoring.segment(answers, c.scoring)
    t1, t2 = mapping.session_types(answers, c.mapping)
    lead = await repo.update_lead(
        user_id, score=sc, segment=seg, session_type=t1, session_type_2=t2,
        status="report_pending", report_path=None, contacted_at=None,
    )
    await repo.set_stage(user_id, flow.STAGE_DONE)
    await repo.log_event(user_id, "segment_assigned", segment=seg, score=sc)
    await send_admin_card(bot, user_id)
    crm.push(user_id)

    await remove_reply_keyboard(bot, user_id)
    if seg == "hot":
        # горячим сначала время разбора, документ вторым (п. 3.7)
        await bot.send_message(
            user_id, c.t("hot_offer", pain_text=pain_text(c, answers)), reply_markup=kb.book(c.t("hot_button"))
        )
        await repo.log_event(user_id, "booking_offered")
        await repo.cancel_jobs(user_id, HOT_REMINDERS)
        await repo.schedule(user_id, "hot_reminder_24h", timedelta(hours=24))
        await repo.schedule(user_id, "hot_reminder_72h", timedelta(hours=72))
    await bot.send_message(user_id, c.t("report_pending"))
    log.info("lead %s: segment=%s score=%s types=%s/%s phone=%s", user_id, seg, sc, t1, t2, bool(lead.phone))


async def send_admin_card(bot: Bot, user_id: int, header: str | None = None) -> None:
    c = get_content()
    u = await repo.get_user(user_id)
    lead = await repo.get_lead(user_id)
    if u is None:
        return
    answers = await repo.get_answers(user_id)
    seg = (lead.segment if lead else None) or "warm"
    text = admin_card(
        c, user_id=user_id, name=u.first_name, username=u.username,
        source=u.source + (f":{u.ref}" if u.ref else ""), answers=answers, segment=seg,
        score=(lead.score if lead else 0) or 0,
        session_type=lead.session_type if lead else None,
        session_type_2=lead.session_type_2 if lead else None,
        phone=lead.phone if lead else None, company=lead.company if lead else None,
    )
    if header:
        text = f"{header}\n\n{text}"
    markup = None if seg == "specialist" else kb.admin_card(c, user_id, u.username)
    await notify.to_admins(bot, text, reply_markup=markup, disable_web_page_preview=True)


# --- ветка специалиста (п. 3.9) ---------------------------------------------
def specialist_docs(need: str | None) -> list[Path]:
    root = get_settings().content_dir / "docs"
    folder = root / need if need and (root / need).is_dir() else root
    if not folder.is_dir():
        return []
    return sorted(
        p for p in folder.iterdir()
        if p.is_file() and not p.name.startswith(".") and p.name.lower() != "readme.md"
    )


async def run_specialist(bot: Bot, user_id: int) -> None:
    c = get_content()
    answers = await repo.get_answers(user_id)
    need = answers.get("specialist_need")
    await repo.update_lead(user_id, segment="specialist", score=0, status="specialist")
    await repo.set_stage(user_id, flow.STAGE_TRAINING)

    await bot.send_message(user_id, c.t("specialist_docs"))
    files = specialist_docs(need)
    for p in files:
        try:
            await bot.send_document(user_id, FSInputFile(p))
        except Exception as e:  # noqa: BLE001
            log.warning("документ %s не отправлен: %s", p.name, e)
    if not files:
        await notify.alert(bot, "docs_empty", "Папка content/docs пуста — специалист остался без документов.")
    await repo.log_event(user_id, "specialist_docs_sent", need=need, files=len(files))
    await repo.log_event(user_id, "segment_assigned", segment="specialist", score=0)

    await bot.send_message(user_id, c.t("specialist_channel"), reply_markup=kb.channel(c))
    await bot.send_message(user_id, c.t("specialist_training_ask"), reply_markup=kb.yes_no(c, "train"))
    await send_admin_card(bot, user_id)
    crm.push(user_id)


# --- разбор: доставка от админа (п. 3.5) ------------------------------------
async def deliver_report(
    bot: Bot, user_id: int, *, from_chat_id: int | None = None, message_id: int | None = None,
    text: str | None = None,
) -> None:
    """Доставить разбор: скопировать сообщение админа (файл/текст) или отправить текст."""
    c = get_content()
    await bot.send_message(user_id, c.t("report_sent_intro"))
    if text is not None:
        await bot.send_message(user_id, text, reply_markup=kb.report_next(c))
        fields = {"report_path": "text", "report_json": {"text": text}}
    else:
        assert from_chat_id is not None and message_id is not None
        await bot.copy_message(user_id, from_chat_id, message_id, reply_markup=kb.report_next(c))
        fields = {"report_path": f"msg:{from_chat_id}:{message_id}"}
    lead = await repo.update_lead(user_id, status="report_sent", verdict="manual", **fields)
    await repo.log_event(user_id, "report_sent", verdict="manual")
    crm.push(user_id)
    if not lead.phone:
        # разбор не держим в заложниках, но после него один раз просим контакт снова
        await ask_contact(bot, user_id, with_later=False)


async def resend_report(bot: Bot, user_id: int) -> bool:
    lead = await repo.get_lead(user_id)
    if not lead or not lead.report_path:
        return False
    markup = kb.report_next(get_content())
    try:
        if lead.report_path == "text" and lead.report_json:
            await bot.send_message(user_id, lead.report_json["text"], reply_markup=markup)
            return True
        if lead.report_path.startswith("msg:"):
            _, chat, msg = lead.report_path.split(":")
            await bot.copy_message(user_id, int(chat), int(msg), reply_markup=markup)
            return True
        return False
    except TelegramBadRequest as e:
        log.warning("разбор %s не переотправлен: %s", user_id, e)
        return False


# --- запись по ссылке (п. 3.7, BOOKING_MODE=url) ----------------------------
async def send_booking_link(bot: Bot, user_id: int) -> None:
    c = get_content()
    await repo.log_event(user_id, "booking_link_clicked")
    await repo.cancel_jobs(user_id, HOT_REMINDERS)
    crm.push(user_id)
    markup = kb.booking_url(c.t("hot_button"))
    if markup is None:
        # BOOKING_URL не задан: человек не должен упереться в пустую кнопку
        await bot.send_message(user_id, c.t("text_forwarded"))
        await notify.to_admins(bot, f"Лид {user_id} хочет записаться на разбор, а BOOKING_URL не задан. Свяжитесь вручную.")
        return
    await bot.send_message(user_id, c.t("hot_booking_url_text"), reply_markup=markup)
    u = await repo.get_user(user_id)
    await notify.to_admins(bot, f"Лид {u.first_name if u else ''} ({user_id}) открыл ссылку записи на разбор.")
