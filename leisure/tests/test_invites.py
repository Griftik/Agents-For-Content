"""Рост через друзей (docs/GROWTH.md): приглашения в Mini App через API §6, уведомления пригласившему, «вдвоём с Имя», «Как прошло?»
обоим, момент рекомендации в боте, ref-коды, show_name / can_write / offer_seen. Нужны БД с seed; id — от pid (tests/ids.py)."""
import os
from datetime import date

import pytest
from sqlalchemy import select, text

from leisure import settings
from leisure.api import invites as inv_service
from leisure.api import services
from leisure.db.models import Decision, GrowthEvent, Invite, InviteAccept, Profile
from leisure.db.session import engine, session_factory
from leisure.worker import messages as msg
from leisure.worker import schedules
from leisure.worker import send as send_mod
from leisure.worker.send import SendResult

from .chat import Chat
from .ids import user_id

H = {"X-API-Key": "test-key"}
INVITER, F1, F2, F3, F4, F5, STRANGER = (user_id(n) for n in (60, 61, 62, 63, 64, 65, 66))
ALL = (INVITER, F1, F2, F3, F4, F5, STRANGER)
DAY = "2026-10-24"


def _db_ok() -> bool:
    try:
        with engine().connect() as c:
            return c.execute(text("select count(*) from events")).scalar() > 0
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _db_ok(), reason="нет доступной БД с seed")


@pytest.fixture
def db():
    with session_factory()() as s:
        yield s


@pytest.fixture
def client(db, monkeypatch):
    from fastapi.testclient import TestClient

    from leisure.api.main import app

    monkeypatch.setattr(settings, "BOT_USERNAME", "dosug_bot")
    monkeypatch.setattr(settings, "MINIAPP_SHORT_NAME", "app")
    for u in ALL:
        services.delete_profile(db, u)
    p = services.get_or_create_profile(db, INVITER, "Аня Иванова", "anya")
    services.update_profile(db, p, {"consent": True, "onboarded": True})
    with TestClient(app) as c:
        yield c
    for u in ALL:
        services.delete_profile(db, u)


@pytest.fixture
def event(db):
    from leisure.db.models import Event
    return db.scalars(select(Event).where(Event.status == "published", text("dates @> ARRAY['2026-10-24','2026-10-25']::date[]"))
                      .order_by(Event.slug).limit(1)).one()


@pytest.fixture
def sent(monkeypatch):
    """Перехват отправки бота: список (user_id, text, rows); результат успешный."""
    out: list[tuple] = []

    def fake(msgs):
        out.extend(msgs)
        return SendResult(len(msgs), [], [])

    monkeypatch.setattr(send_mod, "send_sync", fake)
    monkeypatch.setattr(schedules, "send_sync", fake)
    return out


def _create(client, event, user=INVITER, day=DAY, **extra):
    r = client.post("/api/invites", headers=H, json={"user_id": user, "event_slug": event.slug, "day": day, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _accept(client, code, user, status="going", consent=True, name="Борис Петров", **extra):
    return client.post(f"/api/invites/{code}/accept", headers=H, json={"user_id": user, "status": status, "consent": consent,
                                                                       "name": name, "username": f"u{user}", **extra})


# ── POST /api/invites ──
def test_create_invite_returns_code_urls_and_first_person_text(client, event):
    out = _create(client, event)
    code = out["code"]
    assert len(code) == 8 and set(code) <= set(inv_service.CODE_ALPHABET) and not set(code) & set("01ILOU")
    assert out["url"] == f"https://t.me/dosug_bot/app?startapp=inv_{code}"
    assert out["web_url"].endswith(f"/e/{event.slug}?inv={code}")
    assert out["share_text"].startswith("Иду на «") and out["share_text"].endswith(f"Пойдёшь со мной? {out['url']}") and len(out["share_text"]) <= 300
    assert "суббота, 24 окт" in out["share_text"]
    assert _create(client, event)["code"] == code                              # повтор: тот же код
    assert _create(client, event, day="2026-10-25")["code"] != code           # другой день — другое приглашение
    r = client.post("/api/invites", headers={**H, "X-User-Id": str(INVITER)}, json={"event_slug": event.slug, "day": DAY})
    assert r.status_code == 200 and r.json()["code"] == code                  # user_id заголовком сервера веба
    assert client.post("/api/invites", headers=H, json={"user_id": INVITER, "event_slug": "net-takogo"}).status_code == 404
    assert client.post("/api/invites", headers=H, json={"user_id": INVITER}).status_code == 422
    assert client.post("/api/invites", headers=H, json={"event_slug": event.slug}).status_code == 422
    assert client.post("/api/invites", headers=H, json={"user_id": STRANGER, "event_slug": event.slug}).status_code == 404   # нет профиля
    assert client.post("/api/invites", json={"user_id": INVITER, "event_slug": event.slug}).status_code == 401


def test_share_text_limits_title_and_venue():
    from leisure.core.links import invite_text
    ev = {"title": "Очень длинное название " * 10, "venue": "Площадка " * 10, "dates": [DAY], "time_text": "13:00–15:00",
          "why_fit_hint": "Первое предложение подсказки, довольно длинное и точно больше семидесяти знаков подряд. Второе."}
    t = invite_text(ev, DAY, "https://t.me/b/app?startapp=inv_AAAAAAAA")
    assert len(t) <= 300 and "…" in t.split("\n")[0] and t.endswith("Пойдёшь со мной? https://t.me/b/app?startapp=inv_AAAAAAAA")
    assert "Второе" not in t


# ── GET /api/invites/{code} ──
def test_get_invite_statuses_name_and_ownership(client, db, event):
    out = _create(client, event)
    got = client.get(f"/api/invites/{out['code']}", headers=H, params={"user_id": F1}).json()
    assert got["status"] == "active" and got["inviter_name"] == "Аня" and got["event_slug"] == event.slug and got["is_own"] is False
    assert got["event"]["event"]["slug"] == event.slug and got["event"]["day"] == DAY and got["accepted"] == 0 and got["day"] == DAY
    assert client.get(f"/api/invites/{out['code']}", headers=H, params={"user_id": INVITER}).json()["is_own"] is True
    assert client.put(f"/api/profile/{INVITER}", headers=H, json={"show_name": False}).json()["show_name"] is False
    assert client.get(f"/api/invites/{out['code']}", headers=H).json()["inviter_name"] is None            # имя скрыто
    assert client.get("/api/invites/ZZZZZZZZ", headers=H).status_code == 404
    past = _create(client, event, day="2026-01-05")
    assert client.get(f"/api/invites/{past['code']}", headers=H).json()["status"] == "past"


def test_get_invite_unpublished_and_gone(client, db, event, seed_raw):
    from leisure.db.models import Event
    from leisure.seed.load import upsert_events

    slug = f"zz-test-invite-{os.getpid()}"
    base = next(e for e in seed_raw if DAY in e["dates"])
    upsert_events(db, [{**base, "slug": slug, "title": "Событие для приглашения"}], status="published")
    ev = db.scalar(select(Event).where(Event.slug == slug))
    try:
        code = client.post("/api/invites", headers=H, json={"user_id": INVITER, "event_slug": slug, "day": DAY}).json()["code"]
        ev.status = "draft"
        db.commit()
        assert client.get(f"/api/invites/{code}", headers=H).json()["status"] == "unpublished"
        assert _accept(client, code, F1).status_code == 410
        db.delete(ev)
        db.commit()
        got = client.get(f"/api/invites/{code}", headers=H).json()
        assert got["status"] == "gone" and got["event"] is None and got["event_slug"] == slug
    finally:
        db.expire_all()
        e = db.scalar(select(Event).where(Event.slug == slug))
        if e is not None:
            db.delete(e)
            db.commit()
        db.query(Invite).filter(Invite.event_slug == slug).delete()
        db.commit()


# ── POST /api/invites/{code}/accept ──
def test_accept_needs_consent_creates_profile_and_is_idempotent(client, db, event, sent):
    code = _create(client, event)["code"]
    r = _accept(client, code, F1, consent=False)
    assert r.status_code == 409 and r.json()["detail"] == "consent_required"
    assert db.scalar(select(Decision).where(Decision.user_id == F1)) is None
    r = _accept(client, code, F1)
    assert r.status_code == 200
    body = r.json()
    assert body["decision"]["status"] == "иду" and body["decision"]["day"] == DAY and body["together_with"] == "Аня" and body["profile_state"] == "new"
    db.expire_all()
    p = db.get(Profile, F1)
    assert p.source == "invite" and p.referred_by == INVITER and p.consent_at is not None and p.can_write is False
    assert db.scalar(select(Decision).where(Decision.user_id == F1)).invite_id == db.scalar(select(Invite).where(Invite.code == code)).id
    again = _accept(client, code, F1, consent=False)                                        # повтор без согласия: оно уже есть
    assert again.status_code == 200 and again.json()["decision"] == body["decision"]
    inv = db.scalar(select(Invite).where(Invite.code == code))
    db.refresh(inv)
    assert (inv.opened, inv.accepted) == (1, 1) and len(sent) == 1                          # счётчики и уведомление не дублируются
    assert client.get(f"/api/invites/{code}", headers=H, params={"user_id": F1}).json()["my_status"] == "going"
    # «может» → «иду»: решение меняется, уведомление уходит один раз (только на «иду»)
    assert _accept(client, code, F2, status="maybe").json()["decision"]["status"] == "может" and len(sent) == 1
    assert _accept(client, code, F2, status="going").json()["decision"]["status"] == "иду" and len(sent) == 2
    assert _accept(client, code, F2, status="going").status_code == 200 and len(sent) == 2
    db.refresh(inv)
    assert inv.accepted == 2
    assert _accept(client, code, INVITER).status_code == 400                               # своё приглашение
    assert client.post(f"/api/invites/{code}/accept", headers=H, json={"user_id": F3, "status": "yes"}).status_code == 422
    assert client.post("/api/invites/ZZZZZZZZ/accept", headers=H, json={"user_id": F3, "status": "going", "consent": True}).status_code == 404


def test_accept_of_past_event_is_gone(client, event):
    code = _create(client, event, day="2026-01-05")["code"]
    assert _accept(client, code, F1).status_code == 410


def test_existing_onboarded_profile_keeps_source(client, db, event, sent):
    p = services.get_or_create_profile(db, F1, "Вера", "v")
    services.update_profile(db, p, {"consent": True, "onboarded": True})
    code = _create(client, event)["code"]
    r = _accept(client, code, F1, consent=False)
    assert r.status_code == 200 and r.json()["profile_state"] == "onboarded"
    db.expire_all()
    assert db.get(Profile, F1).source == "organic" and db.get(Profile, F1).referred_by is None and db.get(Profile, F1).can_write is True


# ── уведомление пригласившему ──
def test_inviter_gets_notification_with_name_or_friend(client, db, event, sent):
    code = _create(client, event)["code"]
    _accept(client, code, F1, name="Борис Петров")
    uid, body, rows = sent[0]
    assert uid == INVITER and body == f"Борис идёт с тобой: «{event.title}», суббота, 24 окт." and rows == [[{"text": "Мой план", "callback_data": "pl:s"}]]
    client.put(f"/api/profile/{F2}", headers=H, json={"show_name": False, "name": "Скрытый"})   # профиль создаёт PUT, как в вебе
    _accept(client, code, F2, name="Скрытый")
    client.put(f"/api/profile/{F2}", headers=H, json={"show_name": False})
    # show_name выключен ДО принятия: «Друг идёт с тобой»
    code2 = _create(client, event, day="2026-10-25")["code"]
    _accept(client, code2, F2, name="Скрытый")
    assert sent[-1][1].startswith("Друг идёт с тобой: «")


def test_failed_send_does_not_break_accept_and_worker_retries(client, db, event, monkeypatch):
    calls = []

    def boom(msgs):
        calls.append(msgs)
        raise RuntimeError("Telegram недоступен")

    monkeypatch.setattr(send_mod, "send_sync", boom)
    code = _create(client, event)["code"]
    assert _accept(client, code, F1).status_code == 200                                    # принятие не сломалось
    db.expire_all()
    acc = db.scalar(select(InviteAccept).where(InviteAccept.user_id == F1))
    assert acc.status == "going" and acc.notified_at is None
    got = []
    monkeypatch.setattr(send_mod, "send_sync", lambda m: (got.extend(m), SendResult(len(m), [], []))[1])
    assert inv_service.notify_inviter(db, acc.invite, F1) is True and got[0][0] == INVITER
    db.refresh(acc)
    assert acc.notified_at is not None
    assert inv_service.notify_inviter(db, acc.invite, F1) is False and len(got) == 1       # второй раз не шлём


def test_first_three_friends_one_by_one_then_daily_summary(client, db, event, sent):
    from datetime import datetime, timedelta, timezone

    code = _create(client, event)["code"]
    friends = [F1, F2, F3, F4, F5]
    for i, f in enumerate(friends):
        _accept(client, code, f, name=f"Друг{i}")
    assert len(sent) == 3 and all("идёт с тобой: «" in m[1] and not m[1].startswith("Ещё") for m in sent)   # 4-й и 5-й копятся
    t9 = datetime(2026, 10, 24, 6, 0, tzinfo=timezone.utc)                                 # 09:00 МСК — рано: после утреннего плана
    assert inv_service.notify_many(db, t9, inviter_id=INVITER) == 0 and len(sent) == 3
    t10 = datetime(2026, 10, 24, 7, 5, tzinfo=timezone.utc)                                # 10:05 МСК
    assert inv_service.notify_many(db, t10, inviter_id=INVITER) == 1
    assert sent[-1][1] == f"Ещё 2 друга идут с тобой: «{event.title}», суббота, 24 окт." and sent[-1][2] == [[{"text": "Мой план", "callback_data": "pl:s"}]]
    assert inv_service.notify_many(db, t10 + timedelta(minutes=1), inviter_id=INVITER) == 0 and len(sent) == 4        # в тот же день больше нет
    f6 = user_id(67)
    try:
        _accept(client, code, f6, name="Ещё")
        assert len(sent) == 4                                                              # шестой — тоже в сводку, не по одному
        assert inv_service.notify_many(db, t10 + timedelta(days=1), inviter_id=INVITER) == 1
        assert sent[-1][1] == f"Ещё 1 друг идёт с тобой: «{event.title}», суббота, 24 окт."
    finally:
        services.delete_profile(db, f6)


def test_summary_plural_forms():
    assert msg.invite_joined_many_text(1, "Т", "2026-10-24").startswith("Ещё 1 друг идёт")
    assert msg.invite_joined_many_text(2, "Т", "2026-10-24").startswith("Ещё 2 друга идут")
    assert msg.invite_joined_many_text(5, "Т", "2026-10-24").startswith("Ещё 5 друзей идут")
    assert msg.invite_joined_text(None, "Т", "2026-10-24") == "Друг идёт с тобой: «Т», суббота, 24 окт."


# ── can_write: человек из Mini App, которому бот писать не может ──
def test_friend_without_bot_access_is_skipped_silently_not_deactivated(client, db, event, sent, monkeypatch):
    from datetime import datetime, timezone

    code = _create(client, event)["code"]
    services.set_decision(db, INVITER, event, "иду", day=date(2026, 10, 24))
    _accept(client, code, F1)
    p_inviter = db.get(Profile, INVITER)
    assert db.get(Profile, F1).can_write is False and p_inviter.can_write is True
    forbidden = []

    def blocked(msgs):
        forbidden.append(msgs)
        return SendResult(0, list(range(len(msgs))), [msgs[0][0]])

    monkeypatch.setattr(schedules, "send_sync", blocked)
    monkeypatch.setattr(schedules, "_remindable_profiles", lambda s: [s.get(Profile, F1), s.get(Profile, INVITER)])
    now = datetime(2026, 10, 24, 6, 30, tzinfo=timezone.utc)                                # 09:30 МСК, день события
    assert schedules.job_plan_today(now) == 0 and forbidden                                # попытка была, ответ Forbidden
    db.expire_all()
    assert db.get(Profile, F1).active is True                                             # не «заблокировал»: профиль остаётся активным
    assert db.get(Profile, INVITER).active is False                                       # а у настоящего пользователя бота — выключен
    d = db.scalar(select(Decision).where(Decision.user_id == F1))
    assert d.reminded_at is not None                                                      # и без повторов каждый час
    # право выдано (requestWriteAccess) — веб сообщает PUT can_write
    assert client.put(f"/api/profile/{F1}", headers=H, json={"can_write": True}).json()["can_write"] is True


def test_bot_start_gives_can_write(client, db, event):
    client.put(f"/api/profile/{F1}", headers=H, json={"consent": True})
    p = db.get(Profile, F1)
    p.can_write = False
    db.commit()
    chat = Chat(F1)
    chat.say("/start")
    db.expire_all()
    assert db.get(Profile, F1).can_write is True


# ── план «вдвоём с Имя», «Как прошло?» обоим ──
def test_plan_together_and_feedback_to_both(client, db, event, sent, monkeypatch):
    from datetime import datetime, timezone

    code = _create(client, event)["code"]
    client.put(f"/api/profile/{INVITER}", headers=H, json={})
    services.set_decision(db, INVITER, event, "иду", day=date(2026, 10, 24))
    _accept(client, code, F1, name="Борис Петров")
    mine = client.get(f"/api/plan/{INVITER}", headers=H, params={"today": DAY}).json()
    theirs = client.get(f"/api/plan/{F1}", headers=H, params={"today": DAY}).json()
    assert mine["days"][DAY][0]["companions"] == ["Борис"] and theirs["days"][DAY][0]["companions"] == ["Аня"]
    assert "вдвоём с Борис" in msg.plan_overview_text({**mine, "horizon": []}) and msg.plan_card_text(mine["days"][DAY][0]).count("Вдвоём с Борис.") == 1
    assert "Вдвоём с Аня." in msg.plan_today_text(theirs, DAY)
    client.put(f"/api/profile/{F1}", headers=H, json={"show_name": False})
    # F1 скрыл имя → пригласивший видит «другом»; второй друг → «С друзьями (2)»
    mine = client.get(f"/api/plan/{INVITER}", headers=H, params={"today": DAY}).json()
    assert mine["days"][DAY][0]["companions"] == ["другом"]
    _accept(client, code, F2, name="Вера")
    assert msg.plan_card_text(client.get(f"/api/plan/{INVITER}", headers=H, params={"today": DAY}).json()["days"][DAY][0]).count("С друзьями (2).") == 1
    # «План на сегодня» и «Как прошло?» приходят обоим, в том числе не прошедшему онбординг
    got = []
    monkeypatch.setattr(schedules, "send_sync", lambda m: (got.extend(m), SendResult(len(m), [], []))[1])
    monkeypatch.setattr(schedules, "_remindable_profiles", lambda s: [s.get(Profile, INVITER), s.get(Profile, F1)])
    assert schedules.job_plan_today(datetime(2026, 10, 24, 6, 30, tzinfo=timezone.utc)) == 2
    assert {m[0] for m in got if "План на сегодня" in m[1]} == {INVITER, F1}
    got.clear()
    assert schedules.job_how_was_it(datetime(2026, 10, 25, 9, 5, tzinfo=timezone.utc)) == 2
    assert {m[0] for m in got if "Как прошло?" in m[1]} == {INVITER, F1}


# ── момент рекомендации и низкая оценка (бот) ──
def _rate_setup(db, event, user=INVITER):
    services.set_decision(db, user, event, "иду", day=date(2026, 10, 24))
    chat = Chat(user)
    return chat, chat.send("Как прошло?", msg.rating_keyboard(str(event.id)))


def test_ref_ask_after_4_5_once_in_14_days(client, db, event):
    from datetime import datetime, timedelta, timezone

    chat, mid = _rate_setup(db, event)
    chat.tap(mid, "5 ★")
    ask = chat.world.last_bot_message(INVITER)
    assert ask.text == "Рад, что зашло. Если есть кому посоветовать такие выходные, вот ссылка."
    btn = ask.buttons()[0]
    assert btn["text"] == "Поделиться" and btn["url"].startswith("https://t.me/share/url?") and "startapp%3Dref_" in btn["url"]
    n = len(chat.world.chats[INVITER])
    chat.tap(mid, "4 ★")                                                                  # снова хорошая оценка: рано
    assert len(chat.world.chats[INVITER]) == n
    row = db.scalars(select(GrowthEvent).where(GrowthEvent.user_id == INVITER, GrowthEvent.kind == "ref_ask")).all()
    assert len(row) == 1
    row[0].created_at = datetime.now(timezone.utc) - timedelta(days=15)
    db.commit()
    chat.tap(mid, "5 ★")
    assert chat.world.last_bot_message(INVITER).text.startswith("Рад, что зашло")
    assert db.scalar(select(Invite).where(Invite.inviter_id == INVITER, Invite.kind == "ref")) is not None
    n = len(chat.world.chats[INVITER])
    chat.tap(mid, "3 ★")                                                                  # тройка: ничего
    assert len(chat.world.chats[INVITER]) == n


def test_low_rating_asks_what_was_wrong_with_reasons(client, db, event):
    chat, mid = _rate_setup(db, event)
    chat.tap(mid, "2 ★")
    q = chat.world.last_bot_message(INVITER)
    assert q.text == "Жаль, что не зашло. Что было не так? Это необязательно."
    assert [b["text"] for r in q.rows for b in r] == ["Не моё", "Дорого", "Далеко", "Уже был", "Ещё…"]
    assert not any("startapp=ref" in b.get("url", "") for m in chat.world.chats[INVITER] for b in m.buttons())   # рекомендацию не просим
    chat.tap(q.mid, "Ещё…")
    assert [b["text"] for r in chat.world.get(INVITER, q.mid).rows for b in r] == ["Не то время", "Не та компания"]
    assert chat.tap(q.mid, "Не то время") == "Учту."
    d = db.scalar(select(Decision).where(Decision.user_id == INVITER))
    db.refresh(d)
    assert d.reason == "не в это время" and d.status == "иду" and d.rating == 2             # статус и оценка на месте
    assert chat.world.get(INVITER, q.mid).rows is None


# ── ref-коды и источник профиля ──
def test_ref_link_sets_source_via_api_and_bot_start(client, db):
    ref = client.post("/api/invites", headers=H, json={"user_id": INVITER, "kind": "ref"}).json()
    assert ref["url"] == f"https://t.me/dosug_bot/app?startapp=ref_{ref['code']}" and "Попробуй: " in ref["share_text"]
    assert client.post("/api/invites", headers=H, json={"user_id": INVITER, "kind": "ref"}).json()["code"] == ref["code"]
    r = client.post(f"/api/invites/{ref['code']}/open", headers=H, json={"user_id": F1, "name": "Гость"})
    assert r.status_code == 200
    db.expire_all()
    p = db.get(Profile, F1)
    assert p.source == "ref" and p.referred_by == INVITER and p.can_write is False and p.consent_at is None
    client.post(f"/api/invites/{ref['code']}/open", headers=H, json={"user_id": F1})        # повтор безвреден
    assert db.scalar(select(Invite).where(Invite.code == ref["code"])).opened == 1
    # бот: /start ref_<код> — тот же эффект для нового человека, обычный онбординг
    chat = Chat(F2)
    chat.say(f"/start ref_{ref['code']}")
    db.expire_all()
    assert db.get(Profile, F2).source == "ref" and db.get(Profile, F2).referred_by == INVITER
    assert chat.last_text().startswith("Я подбираю события")
    chat.say(f"/start ref_{ref['code']}")                                                  # не накручивается
    assert db.scalar(select(Invite).where(Invite.code == ref["code"])).opened == 2
    # своя ссылка и чужой формат источник не меняют
    chat3 = Chat(INVITER)
    chat3.say(f"/start ref_{ref['code']}")
    assert db.get(Profile, INVITER).source == "organic"
    chat4 = Chat(F3)
    chat4.say("/start ref_NOSUCH00")
    assert db.get(Profile, F3).source == "organic"


def test_deeplink_to_event_marks_share_source(client, db, event):
    chat = Chat(F4)
    chat.say(f"/start e_{event.slug}")
    db.expire_all()
    assert db.get(Profile, F4).source == "share"


def test_ref_joined_on_consent_counts_as_accepted(client, db):
    ref = client.post("/api/invites", headers=H, json={"user_id": INVITER, "kind": "ref"}).json()
    chat = Chat(F2)
    chat.say(f"/start ref_{ref['code']}")
    chat.tap(chat.last_mid(), "Принять и начать")
    inv = db.scalar(select(Invite).where(Invite.code == ref["code"]))
    db.refresh(inv)
    assert inv.opened == 1 and inv.accepted == 1


# ── профиль: show_name / can_write / offer_seen ──
def test_profile_flags_roundtrip_and_validation(client):
    r = client.put(f"/api/profile/{F1}", headers=H, json={"show_name": False, "can_write": True, "offer_seen": 1})
    assert r.status_code == 200 and (r.json()["show_name"], r.json()["can_write"], r.json()["offer_seen"]) == (False, True, 1)
    assert client.put(f"/api/profile/{F1}", headers=H, json={"offer_seen": 3}).status_code == 422
    assert client.put(f"/api/profile/{F1}", headers=H, json={"offer_seen": 2}).json()["offer_seen"] == 2
    got = client.get(f"/api/profile/{F1}", headers=H).json()
    assert got["offer_seen"] == 2 and got["show_name"] is False and got["source"] == "organic"


# ── метрики ──
def test_growth_metrics_one_request(client, db, event, sent):
    from datetime import datetime, timezone

    since = datetime(2026, 10, 1, tzinfo=timezone.utc)
    code = _create(client, event)["code"]
    _accept(client, code, F1)
    _accept(client, code, F2, status="maybe")
    client.get(f"/api/invites/{code}", headers=H)
    r = client.get("/api/metrics/growth", headers=H, params={"since": since.isoformat()})
    assert r.status_code == 200
    m = r.json()["metrics"]
    assert set(m) == {"invite_share", "acceptance", "activation_invited", "onboarding_invited", "new_via_friends", "virality",
                      "positive_experience", "recommendation", "together_going"}
    assert all({"value", "numerator", "denominator", "target"} <= set(v) for v in m.values())
    c = r.json()["counts"]
    assert c["invites_created"] >= 1 and c["opened"] >= 2 and c["accepted"] >= 2
    assert m["acceptance"]["numerator"] >= 2 and m["activation_invited"]["numerator"] >= 2 and m["new_via_friends"]["numerator"] >= 2
    assert m["together_going"]["numerator"] >= 2
    assert client.get("/api/metrics/growth", params={"since": since.isoformat()}).status_code == 401


def test_deleting_inviter_removes_invite_and_keeps_friend_decision(client, db, event, sent):
    code = _create(client, event)["code"]
    _accept(client, code, F1)
    services.delete_profile(db, INVITER)
    assert client.get(f"/api/invites/{code}", headers=H).status_code == 404
    db.expire_all()
    d = db.scalar(select(Decision).where(Decision.user_id == F1))
    assert d.status == "иду" and d.invite_id is None and db.get(Profile, F1).referred_by is None
