"""API мини-приложения. Экран определяется этапом заявки в БД (users.stage), поэтому
приложение можно закрыть на любом шаге и вернуться туда же — с телефона или компьютера.

POST /api/state            → текущий экран
POST /api/action {type,…}  → действие и новый экран
Каждый запрос несёт initData в заголовке X-Init-Data (подпись Telegram).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiogram import Bot
from aiohttp import web

from bot.config import get_settings
from bot.content import get_content
from bot.db import repo
from bot.services import crm, deeplink, flow, insights, leadflow, notify
from bot.services import subscription as sub
from bot.services.cards import pain_text
from bot.webapp.auth import InitDataError, WebAppUser, validate

log = logging.getLogger(__name__)
BOT_KEY = web.AppKey("bot", Bot)
CONTACT_WAIT_SEC = 6.0


# --- экраны -----------------------------------------------------------------
async def build_state(uid: int) -> dict[str, Any]:
    c = get_content()
    s = get_settings()
    u = await repo.get_user(uid)
    stage = u.stage if u else None
    common = {
        "links": {"consent": s.consent_url or s.privacy_url, "privacy": s.privacy_url,
                  "channel": s.channel_url, "booking": s.booking_url},
        "labels": {"next": c.t("app_next_button"), "close": c.t("app_close_button"),
                   "back": c.t("back_button"), "policy": c.t("app_policy_links")},
    }

    q = flow.stage_question(stage)
    if q:
        question = c.question(q)
        assert question is not None
        answers = await repo.get_answers(uid)
        is_spec = q == c.specialist_need.code
        opts = [{"code": code, "text": text} for code, text in question.options]
        if question.skippable and question.label("skip") is None:
            opts.append({"code": "skip", "text": c.t("skip_button")})
        n = flow.question_number(c, q)
        return {**common, "screen": "question", "question": {
            "code": q, "text": question.text, "options": opts, "selected": answers.get(q),
            "n": n, "total": None if is_spec else len(c.order),
            "progress": None if is_spec else c.t("progress", n=n), "can_back": n > 1,
        }}

    if stage == flow.STAGE_CONTACT:
        first, second = insights.pick(await repo.get_answers(uid), c.insights)
        return {**common, "screen": "contact", "teaser_intro": c.t("teaser_intro"),
                "insights": [first, second], "ask_contact": c.t("ask_contact"),
                "contact_button": c.t("contact_button"), "skip_button": c.t("contact_later_button")}

    if stage == flow.STAGE_COMPANY:
        return {**common, "screen": "company", "text": c.company_text or c.t("ask_company"),
                "placeholder": c.t("app_company_placeholder"), "skip_button": c.t("company_skip_button")}

    if stage == flow.STAGE_TRAINING:
        return {**common, "screen": "specialist", "docs": c.t("specialist_docs"),
                "docs_sent": c.t("app_docs_sent"), "channel_text": c.t("specialist_channel"),
                "channel_button": c.t("specialist_channel_button"),
                "training_ask": c.t("specialist_training_ask"),
                "yes": c.t("yes_button"), "no": c.t("no_button")}

    if stage == flow.STAGE_DONE:
        return {**common, **await _home(uid)}

    return {**common, "screen": "welcome", "text": c.t("welcome"), "owner": s.owner_name,
            "channel": "@" + s.channel_username, "start_button": c.t("start_button"),
            "consent": bool(u and u.consent_at), "consent_label": c.t("consent_off").replace("☐", "").strip(),
            "consent_needed": c.t("consent_needed"), "more": c.t("consent_policy_button")}


async def _home(uid: int) -> dict[str, Any]:
    """Главный экран после заявки: статус разбора, предложение по сегменту, меню."""
    c = get_content()
    u = await repo.get_user(uid)
    lead = await repo.get_lead(uid)
    seg = lead.segment if lead else None
    answers = await repo.get_answers(uid)
    if seg == "specialist":
        status = c.t("app_docs_sent")
    elif lead and lead.report_path:
        status = c.t("app_report_in_chat")
    else:
        status = c.t("report_pending")
    offer = None
    if seg == "hot" and not (lead and lead.contacted_at):
        offer = {"text": c.t("hot_offer", pain_text=pain_text(c, answers)), "button": c.t("hot_button")}
    elif seg == "warm_initiator" and lead and lead.report_path:
        offer = {"text": c.t("initiator_intro"), "button": c.t("warm_button")}
    elif seg == "warm" and lead and lead.report_path:
        offer = {"text": c.t("warm_intro"), "button": c.t("warm_button")}

    subs = None
    o = sub.current_offer()
    if o is not None:
        until = await sub.active_until(uid)
        subs = {"title": sub.t("menu_button"),
                "active": c.t("app_subscription_active", date=sub.fmt_date(until)) if until else None,
                "pitch": None if until else sub.t("pitch", price=o.price_text, days=o.days),
                "button": sub.t("renew_button", days=o.days, price=o.price_text) if until
                else sub.t("buy_button", price=o.price_text),
                "offer_url": get_settings().offer_url or None}

    mb = c.texts["menu_buttons"]
    notify_on = bool(u and u.nurture_enabled)
    return {
        "screen": "home", "title": c.t("already_done"), "status": status, "offer": offer,
        "subscription": subs,
        "menu": {
            "booking": mb["booking"], "restart": c.t("restart_button"),
            "notify": mb["notify_toggle"].format(state=c.t("notify_on") if notify_on else c.t("notify_off")),
            "notify_on": notify_on, "delete": mb["delete"], "delete_confirm": c.t("delete_confirm"),
            "yes": c.t("yes_button"), "no": c.t("no_button"),
        },
    }


# --- действия ---------------------------------------------------------------
async def act(bot: Bot, uid: int, data: dict[str, Any]) -> dict[str, Any]:
    """Выполнить действие. Возвращает доп. поля ответа (toast, open_url, invoice)."""
    c = get_content()
    kind = data.get("type")
    u = await repo.get_user(uid)
    assert u is not None
    stage = u.stage

    if kind == "consent":
        given = bool(data.get("value"))
        await repo.set_consent(uid, given)
        await repo.log_event(uid, "consent_given" if given else "consent_revoked")

    elif kind == "start":
        if u.consent_at is None:
            return {"toast": c.t("consent_needed")}
        if not flow.stage_question(stage):
            await leadflow.start_application(uid)

    elif kind == "answer":
        q, a = str(data.get("q")), str(data.get("a"))
        question = c.question(q)
        if q != flow.stage_question(stage) or question is None:
            return {}  # повторное нажатие или старый экран — просто показать текущий
        if question.label(a) is None and not (question.skippable and a == "skip"):
            return {}
        await repo.save_answer(uid, q, a)
        await repo.log_event(uid, "q_answered", q_code=q)
        if question.branch and question.branch.get(a) != c.specialist_need.code:
            await repo.delete_answers(uid, [c.specialist_need.code])  # передумал быть консультантом
        nxt = flow.next_step(c, q, a)
        if nxt.question:
            await repo.set_stage(uid, flow.q_stage(nxt.question))
        elif nxt.specialist:
            await leadflow.run_specialist(bot, uid)
        elif nxt.finished:
            await leadflow.complete_questions(uid)

    elif kind == "back":
        q = flow.stage_question(stage)
        prev = flow.prev_question(c, q, {}) if q else None
        if prev:
            await repo.set_stage(uid, flow.q_stage(prev))

    elif kind == "contact_check":
        # телефон приходит в чат отдельным сообщением от Telegram — ждём его несколько секунд
        loop = asyncio.get_running_loop()
        deadline = loop.time() + CONTACT_WAIT_SEC
        while loop.time() < deadline:
            lead = await repo.get_lead(uid)
            if lead and lead.phone:
                break
            await asyncio.sleep(0.3)
        else:
            return {"toast": c.t("app_contact_wait")}
        if (await repo.get_user(uid)).stage == flow.STAGE_CONTACT:  # type: ignore[union-attr]
            await repo.set_stage(uid, flow.STAGE_COMPANY)

    elif kind == "contact_skip":
        if stage == flow.STAGE_CONTACT:
            await repo.log_event(uid, "contact_skipped", reason="button")
            await repo.set_stage(uid, flow.STAGE_COMPANY)

    elif kind == "company":
        if stage == flow.STAGE_COMPANY:
            text = str(data.get("text") or "").strip()
            if text:
                await repo.update_lead(uid, company=text[:256])
            await leadflow.finalize(bot, uid)

    elif kind == "training":
        if stage == flow.STAGE_TRAINING:
            yes = bool(data.get("value"))
            await repo.save_answer(uid, "training_announce", "yes" if yes else "no")
            await repo.log_event(uid, "specialist_training", answer="yes" if yes else "no")
            await repo.set_stage(uid, flow.STAGE_DONE)
            if yes:
                who = f"@{u.username}" if u.username else f"id {uid}"
                await notify.to_admins(bot, f"Специалист {u.first_name or ''} ({who}) хочет анонс обучения фасилитаторов.")

    elif kind == "book":
        await leadflow.booking_clicked(bot, uid)
        url = get_settings().booking_url
        return {"open_url": url} if url else {"toast": c.t("text_forwarded")}

    elif kind == "restart":
        await leadflow.start_application(uid)

    elif kind == "notify":
        enabled = bool(data.get("value"))
        await repo.set_nurture(uid, enabled)
        if not enabled:
            await repo.cancel_jobs(uid, leadflow.HOT_REMINDERS)
            await repo.log_event(uid, "unsubscribed")

    elif kind == "delete":
        await repo.forget_user(uid)
        await repo.log_event(uid, "deleted")
        crm.push(uid)
        await notify.to_admins(bot, f"Пользователь {uid} удалил свои данные (из приложения).")
        return {"toast": c.t("delete_done")}

    elif kind == "invoice":
        link = await sub.invoice_link(bot, uid)
        return {"invoice": link} if link else {"toast": sub.t("unavailable")}

    return {}


# --- HTTP -------------------------------------------------------------------
async def _auth(request: web.Request) -> WebAppUser:
    s = get_settings()
    try:
        return validate(request.headers.get("X-Init-Data", ""), s.bot_token, s.initdata_max_age_sec)
    except InitDataError as e:
        raise web.HTTPUnauthorized(text=str(e)) from e


async def _ensure_user(wu: WebAppUser) -> None:
    source, ref = deeplink.parse(wu.start_param)
    _, created = await repo.upsert_user(wu.id, wu.username, wu.first_name, source, ref)
    if created:  # пришёл сразу в приложение по ссылке ?startapp=…, минуя /start
        await repo.log_event(wu.id, "start", arg=wu.start_param or "", via="app")
        await repo.set_stage(wu.id, flow.STAGE_WELCOME)


async def state_handler(request: web.Request) -> web.Response:
    wu = await _auth(request)
    await _ensure_user(wu)
    return web.json_response(await build_state(wu.id))


async def action_handler(request: web.Request) -> web.Response:
    wu = await _auth(request)
    await _ensure_user(wu)
    try:
        data = await request.json()
    except ValueError:
        raise web.HTTPBadRequest(text="нужен JSON") from None
    extra = await act(request.app[BOT_KEY], wu.id, data if isinstance(data, dict) else {})
    return web.json_response({**await build_state(wu.id), **extra})
