#!/usr/bin/env python3
"""Контентщик (агент #3) — бот канала @neurostrategy.

Голос/текст → расшифровка (OpenRouter) → пост в стиле Евгения (OpenRouter) →
превью с кнопками → публикация в Telegram сразу или по расписанию.
Всё через ОДИН ключ OpenRouter. Секреты — из .env через core.config.

Запуск как службы:  python -m agents.contentmaker
"""
from __future__ import annotations

import base64
import os
import tempfile
from datetime import datetime, timedelta, timezone

import httpx
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from core import config
from core.logging_setup import setup_logging

logger = setup_logging("contentmaker")

OPENROUTER_URL = "https://openrouter.ai/api/v1"
MSK = timezone(timedelta(hours=3))
CAPTION_LIMIT = 1024  # лимит подписи к фото в Telegram

# Резолвится в main() после проверки .env.
_ALLOWED_USER = 0

CHANNEL_FOOTER = """

——
• [Обо мне](https://t.me/neurostrategy/903) • [Трансформация себя](https://t.me/neurostrategy/921) • [Трансформация компании](https://t.me/neurostrategy/922) • [Схемы и методология](https://t.me/neurostrategy/756) • [Видео и подкасты](https://t.me/neurostrategy/664)"""

SYSTEM_PROMPT = """Ты — Евгений Григорьев, основатель DT-Team, стратег и игротехник.
Пишешь посты для Telegram-канала @neurostrategy.

ТВОЙ СТИЛЬ (на основе 690 реальных постов):
- Начинаешь с жирного заголовка **вот так** или интригующей фразы
- Пишешь от первого лица, искренне и без пафоса
- Делишься реальными кейсами, инсайтами, личным опытом
- Короткие абзацы — по 1-3 предложения
- Иногда задаёшь вопрос аудитории в конце
- Эмодзи органично и умеренно (🔥 💡 ✔️ 🚀)
- Тон: живой, тёплый, профессиональный, иногда уязвимый
- Темы: трансформация бизнеса, стратегия, личное развитие, кейсы клиентов
- Длина: 150-400 слов

Преврати идею/расшифровку голосового в готовый пост.
Сохрани смысл и эмоцию оригинала, но причеши структуру и стиль.
НЕ добавляй плашку и хэштеги.
Пиши ТОЛЬКО текст поста, без пояснений."""

# ─── Состояние диалога (в памяти; устойчивость к рестарту — Слайс 3) ───
user_state: dict[int, dict] = {}


def get_state(uid: int) -> dict:
    return user_state.setdefault(uid, {})


def is_allowed(uid: int) -> bool:
    return _ALLOWED_USER == 0 or uid == _ALLOWED_USER


# ─── AI: всё через OpenRouter ────────────────────────────────────────────────

async def generate_post(idea: str) -> str:
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            f"{OPENROUTER_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {config.openrouter_key()}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.POST_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Идея для поста:\n\n{idea}"},
                ],
                "max_tokens": 1200,
            },
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()


async def transcribe_voice(file_path: str) -> str:
    """Расшифровка голоса через OpenRouter STT (тот же ключ).

    Эндпоинт /audio/transcriptions, base64-режим. Формат ogg — родной для
    голосовых Telegram и есть в списке поддерживаемых. Модель — VOICE_MODEL,
    так что заменить её можно через .env, не трогая код.
    """
    with open(file_path, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode("utf-8")
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            f"{OPENROUTER_URL}/audio/transcriptions",
            headers={
                "Authorization": f"Bearer {config.openrouter_key()}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.VOICE_MODEL,
                "input_audio": {"data": audio_b64, "format": "ogg"},
                "language": "ru",
            },
        )
        r.raise_for_status()
        return r.json()["text"]


# ─── Клавиатуры ──────────────────────────────────────────────────────────────

def main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[KeyboardButton("✍️ Новый пост")]], resize_keyboard=True)


def actions_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Опубликовать", callback_data="publish"),
         InlineKeyboardButton("⏰ Запланировать", callback_data="schedule")],
        [InlineKeyboardButton("✏️ Исправить", callback_data="edit"),
         InlineKeyboardButton("🔄 Заново", callback_data="regen")],
        [InlineKeyboardButton("🖼 Фото", callback_data="photo"),
         InlineKeyboardButton("❌ Отмена", callback_data="cancel")],
    ])


def schedule_kb() -> InlineKeyboardMarkup:
    now = datetime.now(MSK)
    rows = []
    for h in [9, 12, 15, 18, 21]:
        t = now.replace(hour=h, minute=0, second=0, microsecond=0)
        if t <= now:
            t += timedelta(days=1)
        rows.append([InlineKeyboardButton(t.strftime("🗓 %d.%m в %H:%M"),
                                          callback_data=f"s_{t.isoformat()}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="back")])
    return InlineKeyboardMarkup(rows)


# ─── Публикация (с фолбэком на обычный текст) ────────────────────────────────

async def _send_text(bot, chat_id, text: str) -> None:
    try:
        await bot.send_message(chat_id, text, parse_mode="Markdown")
    except BadRequest as e:
        logger.warning("Markdown не прошёл (%s) — шлю обычным текстом", e)
        await bot.send_message(chat_id, text)


async def _send_post(bot, chat_id, text: str, photo: str | None = None) -> None:
    """Публикует пост. Учитывает лимит подписи к фото и сбои разметки."""
    if not photo:
        await _send_text(bot, chat_id, text)
        return
    if len(text) <= CAPTION_LIMIT:
        try:
            await bot.send_photo(chat_id, photo, caption=text, parse_mode="Markdown")
        except BadRequest as e:
            logger.warning("Подпись с разметкой не прошла (%s) — обычным текстом", e)
            await bot.send_photo(chat_id, photo, caption=text)
    else:
        # Длинный пост не влезает в подпись к фото — шлём фото и текст отдельно.
        await bot.send_photo(chat_id, photo)
        await _send_text(bot, chat_id, text)


# ─── Хендлеры ────────────────────────────────────────────────────────────────

async def start(update: Update, ctx) -> None:
    if not is_allowed(update.effective_user.id):
        return
    await update.message.reply_text(
        "Привет, Женя! 👋\n\nПросто *надиктуй голосовое* или напиши идею — "
        "я сделаю из неё пост в твоём стиле.\n\n"
        "Потом покажу превью: публиковать сразу или по расписанию.",
        parse_mode="Markdown", reply_markup=main_kb())


async def on_text(update: Update, ctx) -> None:
    uid = update.effective_user.id
    if not is_allowed(uid):
        return
    text = update.message.text
    st = get_state(uid)
    if text == "✍️ Новый пост":
        st.clear()
        await update.message.reply_text("Надиктуй или напиши идею 🎙", reply_markup=main_kb())
        return
    if st.get("stage") == "editing":
        st["draft"] = text
        st["stage"] = None
        await preview(update, ctx)
        return
    await make_post(update, ctx, text)


async def on_voice(update: Update, ctx) -> None:
    uid = update.effective_user.id
    if not is_allowed(uid):
        return
    msg = await update.message.reply_text("🎙 Слушаю голосовое...")
    voice = update.message.voice or update.message.audio
    tg_file = await ctx.bot.get_file(voice.file_id)
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        await tg_file.download_to_drive(tmp.name)
        path = tmp.name
    try:
        await msg.edit_text("📝 Расшифровываю...")
        text = await transcribe_voice(path)
        await msg.edit_text(f"📝 Расшифровка:\n\n_{text}_\n\n⏳ Делаю пост...",
                            parse_mode="Markdown")
        await make_post(update, ctx, text, existing_msg=msg)
    except Exception as e:
        logger.error("voice error: %s", e)
        await msg.edit_text(f"❌ Ошибка расшифровки: {e}\n\nПопробуй текстом.")
    finally:
        os.unlink(path)


async def make_post(update: Update, ctx, idea: str, existing_msg=None) -> None:
    uid = update.effective_user.id
    st = get_state(uid)
    st["idea"] = idea
    msg = existing_msg or await update.message.reply_text("⏳ Пишу пост...")
    try:
        st["draft"] = await generate_post(idea)
        await msg.delete()
        await preview(update, ctx)
    except Exception as e:
        logger.error("gen error: %s", e)
        await msg.edit_text(f"❌ Ошибка генерации: {e}")


async def preview(update: Update, ctx) -> None:
    uid = update.callback_query.from_user.id if update.callback_query else update.effective_user.id
    st = get_state(uid)
    draft = st.get("draft", "")
    photo_mark = "🖼 с фото" if st.get("photo") else ""
    txt = (f"📋 *Превью* {photo_mark}\n{'─' * 30}\n\n"
           f"{draft}{CHANNEL_FOOTER}\n\n{'─' * 30}\n_{len(draft)} симв._")
    tgt = update.callback_query.message if update.callback_query else update.message
    await tgt.reply_text(txt, parse_mode="Markdown", reply_markup=actions_kb())


async def on_photo(update: Update, ctx) -> None:
    uid = update.effective_user.id
    if not is_allowed(uid):
        return
    st = get_state(uid)
    st["photo"] = update.message.photo[-1].file_id
    if st.get("draft"):
        await update.message.reply_text("🖼 Фото добавлено!")
        await preview(update, ctx)
    else:
        await update.message.reply_text("🖼 Фото сохранил. Теперь надиктуй идею поста.")


async def on_callback(update: Update, ctx) -> None:
    q = update.callback_query
    uid = q.from_user.id
    if not is_allowed(uid):
        return
    await q.answer()
    st = get_state(uid)
    d = q.data
    if d == "publish":
        await publish(q, ctx, st)
    elif d == "schedule":
        await q.message.reply_text("Когда опубликовать?", reply_markup=schedule_kb())
    elif d.startswith("s_"):
        dt = datetime.fromisoformat(d[2:])
        delay = max((dt - datetime.now(MSK)).total_seconds(), 60)
        ctx.job_queue.run_once(sched_publish, when=delay,
                               data={"state": dict(st), "chat": q.message.chat_id})
        await q.message.reply_text(
            f"⏰ Запланировано на *{dt.strftime('%d.%m в %H:%M МСК')}* ✅",
            parse_mode="Markdown", reply_markup=main_kb())
        st.clear()
    elif d == "edit":
        st["stage"] = "editing"
        await q.message.reply_text("✏️ Пришли исправленный текст:")
    elif d == "regen":
        m = await q.message.reply_text("🔄 Переписываю...")
        try:
            st["draft"] = await generate_post(st.get("idea", st.get("draft", "")))
            await m.delete()
            await preview(update, ctx)
        except Exception as e:
            await m.edit_text(f"❌ {e}")
    elif d == "photo":
        await q.message.reply_text("🖼 Пришли фото:")
    elif d == "back":
        await preview(update, ctx)
    elif d == "cancel":
        st.clear()
        await q.message.reply_text("Отменено 👌", reply_markup=main_kb())


async def publish(q, ctx, st) -> None:
    draft = st.get("draft", "")
    photo = st.get("photo")
    try:
        await _send_post(ctx.bot, config.CHANNEL_ID, draft + CHANNEL_FOOTER, photo)
        st.clear()
        await q.message.reply_text("🚀 Опубликовано в @neurostrategy!", reply_markup=main_kb())
    except Exception as e:
        logger.error("publish error: %s", e)
        await q.message.reply_text(f"❌ Ошибка: {e}")


async def sched_publish(ctx) -> None:
    data = ctx.job.data
    st = data["state"]
    draft = st.get("draft", "")
    photo = st.get("photo")
    try:
        await _send_post(ctx.bot, config.CHANNEL_ID, draft + CHANNEL_FOOTER, photo)
        await ctx.bot.send_message(data["chat"], "✅ Запланированный пост опубликован!")
    except Exception as e:
        logger.error("sched publish error: %s", e)
        await ctx.bot.send_message(data["chat"], f"❌ Ошибка: {e}")


def main() -> None:
    # Падаем сразу с понятной ошибкой, если .env не заполнен.
    token = config.bot_token()
    config.openrouter_key()
    global _ALLOWED_USER
    _ALLOWED_USER = config.allowed_user_id()

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(CallbackQueryHandler(on_callback))
    logger.info("Контентщик запущен, публикует в %s", config.CHANNEL_ID)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
