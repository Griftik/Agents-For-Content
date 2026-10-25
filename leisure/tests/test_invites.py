"""Рост через друзей (docs/GROWTH.md): приглашения в Mini App через API §6, уведомления пригласившему, «вдвоём с Имя», «Как прошло?»
обоим, момент рекомендации в боте, ref-коды, show_name / can_write / offer_seen. Нужны БД с seed; id — от pid (tests/ids.py)."""
import os
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select, text

from leisure import settings
from leisure.api import invites as inv_service
from leisure.api import services
from leisure.core.timeutil import day_phrase
from leisure.db.models import Decision, GrowthEvent, Invite, InviteAccept, Profile
from leisure.db.session import engine, session_factory
from .ids import user_id

H = {"X-API-Key": "test-key"}
INVITER, F1, F2, F3, F4, F5, STRANGER = (user_id(n) for n in (60, 61, 62, 63, 64, 65, 66))
ALL = (INVITER, F1, F2, F3, F4, F5, STRANGER)


def _pick_days() -> tuple[str, str, str]:
    """Два подряд идущих будущих дня, на которые в seed есть одно и то же событие (статусы приглашений считаются от реальной даты)."""
    try:
        with engine().connect() as c:
            row = c.execute(text("select d::date from events e, unnest(e.dates) d where e.status = 'published' and d > current_date "
                                 "and (d + 1) = any(e.dates) order by d limit 1")).first()
        d0 = row[0]
    except Exception:  # noqa: BLE001
        d0 = date(2026, 10, 31)
    return d0.isoformat(), (d0 + timedelta(days=1)).isoformat(), (d0 + timedelta(days=2)).isoformat()


DAY, DAY1, DAY2 = _pick_days()


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
    return db.scalars(select(Event).where(Event.status == "published", text(f"dates @> ARRAY['{DAY}','{DAY1}']::date[]"))
                      .order_by(Event.slug).limit(1)).one()


@pytest.fixture
def sent():
    """Версия 2: отдельного канала уведомлений нет. Фикстура оставлена, чтобы не трогать сигнатуры: всегда пустой список."""
    return []


def _notified(db, code: str) -> int:
    """Сколько принявших отмечено notified_at (пригласивший увидит «идёт с тобой» в плане)."""
    db.expire_all()
    inv = db.scalar(select(Invite).where(Invite.code == code))
    return sum(1 for a in inv.accepts if a.notified_at is not None)


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
    assert out["url"] == f"http://localhost:3000/e/{event.slug}?inv={code}" and out["web_url"] == out["url"]
    assert out["web_url"].endswith(f"/e/{event.slug}?inv={code}")
    assert out["share_text"].startswith("Иду на «") and out["share_text"].endswith(f"Пойдёшь со мной? {out['url']}") and len(out["share_text"]) <= 300
    assert day_phrase(DAY) in out["share_text"]
    assert _create(client, event)["code"] == code                              # повтор: тот же код
    assert _create(client, event, day=DAY1)["code"] != code           # другой день — другое приглашение
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
        assert got["status"] == "unpublished" and got["event"] is None and got["event_slug"] == slug     # событие удалено
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
    assert (inv.opened, inv.accepted) == (1, 1) and _notified(db, code) == 1                          # счётчики и уведомление не дублируются
    assert client.get(f"/api/invites/{code}", headers=H, params={"user_id": F1}).json()["my_status"] == "going"
    # «может» → «иду»: решение меняется, уведомление уходит один раз (только на «иду»)
    assert _accept(client, code, F2, status="maybe").json()["decision"]["status"] == "может" and _notified(db, code) == 1
    assert _accept(client, code, F2, status="going").json()["decision"]["status"] == "иду" and _notified(db, code) == 2
    assert _accept(client, code, F2, status="going").status_code == 200 and _notified(db, code) == 2
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
    assert db.get(Profile, F1).source == "organic" and db.get(Profile, F1).referred_by is None and db.get(Profile, F1).can_write is False


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


def test_inviter_deleted_gives_gone_status_and_friend_can_still_accept(client, db, event, sent):
    """Пригласивший удалил профиль: ссылка живая, статус gone, имени нет; связи с ним в данных не остаётся."""
    code = _create(client, event)["code"]
    _accept(client, code, F1)
    services.delete_profile(db, INVITER)
    got = client.get(f"/api/invites/{code}", headers=H, params={"user_id": F2})
    assert got.status_code == 200
    g = got.json()
    assert g["status"] == "gone" and g["inviter_name"] is None and g["is_own"] is False and g["event"]["event"]["slug"] == event.slug
    db.expire_all()
    d = db.scalar(select(Decision).where(Decision.user_id == F1))
    assert d.status == "иду" and d.invite_id is not None and db.get(Profile, F1).referred_by is None
    r = _accept(client, code, F2)
    assert r.status_code == 200 and r.json()["together_with"] is None and r.json()["decision"]["status"] == "иду"
    assert services.companion_names(db, F2, db.scalar(select(Decision).where(Decision.user_id == F2))) == []
    db.expire_all()
    assert db.get(Profile, F2).source == "invite" and db.get(Profile, F2).referred_by is None
    assert client.get("/api/invites/ZZZZZZZZ", headers=H).status_code == 404   # а неизвестный код — по-прежнему 404


def test_declined_records_without_decision_or_consent(client, db, event, sent):
    code = _create(client, event)["code"]
    r = _accept(client, code, F1, status="declined", consent=False)
    assert r.status_code == 200 and r.json()["decision"] is None and r.json()["profile_state"] == "new"
    db.expire_all()
    # без согласия профиля и записи принятия нет: отказ — строка журнала по коду, без user_id
    assert db.get(Profile, F1) is None and db.scalar(select(InviteAccept).where(InviteAccept.user_id == F1)) is None
    assert db.scalar(select(Decision).where(Decision.user_id == F1)) is None
    ev = db.scalars(select(GrowthEvent).where(GrowthEvent.kind == "invite_declined", GrowthEvent.invite_code == code)).all()
    assert len(ev) == 1 and ev[0].user_id is None
    assert db.scalar(select(Invite).where(Invite.code == code)).accepted == 0 and _notified(db, code) == 0
    assert _accept(client, code, F1, status="declined", consent=False).status_code == 200            # повтор безвреден
    assert db.get(Profile, F1) is None
    # человек с согласием: запись declined создаётся
    p3 = services.get_or_create_profile(db, F3, "Согласная", "s")
    services.update_profile(db, p3, {"consent": True})
    assert _accept(client, code, F3, status="declined", consent=False).json()["decision"] is None
    db.expire_all()
    acc = db.scalar(select(InviteAccept).where(InviteAccept.user_id == F3))
    assert acc.status == "declined" and acc.accepted_at is None and db.scalar(select(Decision).where(Decision.user_id == F3)) is None
    # потом передумал и пошёл: declined уступает going
    assert _accept(client, code, F1).json()["decision"]["status"] == "иду"
    # а принявшего declined не откатывает
    r = _accept(client, code, F1, status="declined", consent=False)
    assert r.json()["decision"]["status"] == "иду"
    db.expire_all()
    assert db.scalar(select(InviteAccept).where(InviteAccept.user_id == F1)).status == "going"
    assert _accept(client, code, INVITER, status="declined").status_code == 400
    assert client.get(f"/api/invites/{code}", headers=H, params={"user_id": F2}).json()["status"] == "active"
    # declined на прошедшем событии тоже записывается: человек уходит в свою подборку
    past = _create(client, event, day="2026-01-05")["code"]
    assert _accept(client, past, F2, status="declined", consent=False).status_code == 200


def test_put_profile_ref_code_sets_source_once(client, db):
    ref = client.post("/api/invites", headers=H, json={"user_id": INVITER, "kind": "ref"}).json()["code"]
    r = client.put(f"/api/profile/{F1}", headers=H, json={"name": "Гость", "ref_code": ref})
    assert r.status_code == 200 and r.json()["source"] == "ref"
    db.expire_all()
    p = db.get(Profile, F1)
    assert p.source == "ref" and p.referred_by == INVITER and p.can_write is False
    inv = db.scalar(select(Invite).where(Invite.code == ref))
    assert inv.opened == 1
    client.put(f"/api/profile/{F1}", headers=H, json={"ref_code": ref})                 # повтор: ничего не накручивается
    db.refresh(inv)
    assert inv.opened == 1
    client.put(f"/api/profile/{F2}", headers=H, json={"ref_code": "NOSUCH00"})           # чужой код игнорируется
    client.put(f"/api/profile/{INVITER}", headers=H, json={"ref_code": ref})              # свой — тоже
    db.expire_all()
    assert db.get(Profile, F2).source == "organic" and db.get(Profile, INVITER).source == "organic"
    # профиль, уже пришедший по приглашению, источник не меняет
    p3 = client.put(f"/api/profile/{F3}", headers=H, json={"ref_code": ref}).json()
    assert p3["source"] == "ref" and client.put(f"/api/profile/{F3}", headers=H, json={"ref_code": "ZZZZZZZZ"}).json()["source"] == "ref"
    assert client.put(f"/api/profile/{F4}", headers=H, json={"ref_code": "123456789"}).status_code == 422


def test_catalog_gives_category_values_for_web(client):
    from leisure.core.catalog import ALL_CATS, CATEGORY_VALUES, VALUES
    cat = client.get("/api/catalog").json()
    assert cat["category_values"] == CATEGORY_VALUES and set(cat["category_values"]) == set(ALL_CATS)
    assert all(v in VALUES for d in cat["category_values"].values() for v in d)
    assert cat["proposed_n"] == 8 and cat["proposed_top"] == 5


# ── ТЗ-10: has_consent, открытие без согласия, score/why приглашения, offer_due ──
def _anon_opens(db, code):
    return db.scalar(select(func.count()).select_from(GrowthEvent).where(GrowthEvent.kind == "invite_open", GrowthEvent.invite_code == code))


def test_profile_get_gives_has_consent_and_offer_due(client):
    client.put(f"/api/profile/{F1}", headers=H, json={"name": "Гость"})
    p = client.get(f"/api/profile/{F1}", headers=H).json()
    assert p["has_consent"] is False and p["offer_due"] is None
    assert client.put(f"/api/profile/{F1}", headers=H, json={"consent": True}).json()["has_consent"] is True
    assert client.get(f"/api/profile/{F1}", headers=H).json()["has_consent"] is True
    assert client.get(f"/api/profile/{INVITER}", headers=H).json()["has_consent"] is True


def test_open_without_consent_creates_no_profile_and_counts_in_growth_events(client, db, event):
    code = _create(client, event)["code"]
    ref = client.post("/api/invites", headers=H, json={"user_id": INVITER, "kind": "ref"}).json()["code"]
    inv = db.scalar(select(Invite).where(Invite.code == code))
    # совсем новый человек
    r = client.post(f"/api/invites/{code}/open", headers=H, json={"user_id": F1, "name": "Борис"})
    assert r.status_code == 200 and r.json()["status"] == "active" and r.json()["my_status"] is None and r.json()["event"] is not None
    client.post(f"/api/invites/{code}/open", headers=H, json={"user_id": F1})
    db.expire_all()
    assert db.get(Profile, F1) is None and db.scalar(select(InviteAccept).where(InviteAccept.user_id == F1)) is None
    assert _anon_opens(db, code) == 1 and inv.opened == 0                 # один человек на ссылку — одна строка
    gevent = db.scalar(select(GrowthEvent).where(GrowthEvent.invite_code == code))
    assert gevent.user_id is None and str(F1) not in (gevent.visitor or "")      # user_id в журнале нет, только псевдоним
    # ref-ссылка: то же
    assert client.post(f"/api/invites/{ref}/open", headers=H, json={"user_id": F2}).status_code == 200
    db.expire_all()
    assert db.get(Profile, F2) is None and _anon_opens(db, ref) == 1
    # профиль есть, а согласия нет (создан PUT'ом): записи InviteAccept нет, профиль не меняется
    client.put(f"/api/profile/{F3}", headers=H, json={"name": "Без согласия"})
    client.post(f"/api/invites/{code}/open", headers=H, json={"user_id": F3})
    db.expire_all()
    assert db.scalar(select(InviteAccept).where(InviteAccept.user_id == F3)) is None and _anon_opens(db, code) == 2
    assert db.get(Profile, F3).source == "organic"
    # принятие без согласия: 409 и по-прежнему ни профиля, ни записей
    assert _accept(client, code, F1, consent=False).status_code == 409
    db.expire_all()
    assert db.get(Profile, F1) is None and db.scalar(select(InviteAccept).where(InviteAccept.user_id == F1)) is None
    # дал согласие: профиль и запись создаются, человек считается новым
    assert _accept(client, code, F1).status_code == 200
    db.expire_all()
    acc = db.scalar(select(InviteAccept).where(InviteAccept.user_id == F1))
    assert db.get(Profile, F1).consent_at is not None and acc.was_new is True and acc.status == "going"
    assert _anon_opens(db, code) == 1                                   # F1 теперь считается по invite_accepts, его строка журнала снята
    # человек с согласием: открытие учитывается как раньше (InviteAccept), журнал не растёт
    p = db.get(Profile, F4) or services.get_or_create_profile(db, F4, "Дарья", "d")
    services.update_profile(db, p, {"consent": True})
    client.post(f"/api/invites/{code}/open", headers=H, json={"user_id": F4})
    db.expire_all()
    acc4 = db.scalar(select(InviteAccept).where(InviteAccept.user_id == F4))
    assert acc4 is not None and acc4.status == "opened" and acc4.was_new is False and _anon_opens(db, code) == 1
    # своё открытие не считается
    client.post(f"/api/invites/{code}/open", headers=H, json={"user_id": INVITER})
    assert _anon_opens(db, code) == 1
    assert client.get("/api/metrics/growth", headers=H).json()["counts"]["opened_without_consent"] >= 2


def test_invite_gives_score_and_why_only_for_ready_profile(client, db, event):
    code = _create(client, event)["code"]
    url = f"/api/invites/{code}"
    # не настроен, без профиля, без user_id: null
    client.put(f"/api/profile/{F1}", headers=H, json={"consent": True, "name": "Новичок"})
    for params in ({}, {"user_id": F1}, {"user_id": F2}):
        body = client.get(url, headers=H, params=params).json()
        assert body["score"] is None and body["why"] is None
    # готовый профиль: тот же расчёт, что в дайджесте для веба
    client.put(f"/api/profile/{F2}", headers=H, json={"consent": True, "name": "Готовая", "onboarded": True,
                                                       "values": {"Творчество": 5, "Красота/эстетика": 4}})
    body = client.get(url, headers=H, params={"user_id": F2}).json()
    assert isinstance(body["score"], int) and isinstance(body["why"], list)
    alls = client.get(f"/api/digest/{F2}/all", headers=H, params={"today": DAY}).json()
    mine = next(e for e in alls if e["slug"] == event.slug)
    assert body["score"] == mine["score"] and body["why"] == mine["why"]
    assert body["event"]["score"] == body["score"]
    # у пригласившего (готовый профиль) тоже есть
    assert isinstance(client.get(url, headers=H, params={"user_id": INVITER}).json()["score"], int)


def test_accept_sets_offer_due_to_event_day_plus_one_once(client, db, event, sent):
    code = _create(client, event)["code"]
    assert _accept(client, code, F1, status="declined", consent=False).status_code == 200
    assert client.get(f"/api/profile/{F1}", headers=H).status_code == 404                     # отказ профиль и срок не создаёт
    assert _accept(client, code, F1, status="maybe").status_code == 200
    assert client.get(f"/api/profile/{F1}", headers=H).json()["offer_due"] == DAY1
    other = _create(client, event, day=DAY1)["code"]
    assert _accept(client, other, F1).status_code == 200
    assert client.get(f"/api/profile/{F1}", headers=H).json()["offer_due"] == DAY1    # не сдвигается
    assert _accept(client, other, F2).status_code == 200
    assert client.get(f"/api/profile/{F2}", headers=H).json()["offer_due"] == DAY2
    # PUT offer_seen работает как раньше, offer_due им не трогается
    r = client.put(f"/api/profile/{F2}", headers=H, json={"offer_seen": 1}).json()
    assert r["offer_seen"] == 1 and r["offer_due"] == DAY2


def _gm(client):
    j = client.get("/api/metrics/growth", headers=H).json()["metrics"]
    return {k: (j[k]["numerator"], j[k]["denominator"]) for k in ("acceptance", "activation_invited", "recommendation")}


def test_growth_metrics_count_openers_without_consent_in_denominators(client, db, event, sent):
    code = _create(client, event)["code"]
    ref = client.post("/api/invites", headers=H, json={"user_id": INVITER, "kind": "ref"}).json()["code"]
    # человек с профилем и согласием (не новый)
    p4 = services.get_or_create_profile(db, F4, "Дарья", "d")
    services.update_profile(db, p4, {"consent": True})
    before = _gm(client)
    op = lambda u, c=code: client.post(f"/api/invites/{c}/open", headers=H, json={"user_id": u})   # noqa: E731
    op(F1); op(F1)                                                    # открыл без согласия, дважды: считается один раз
    op(F2); assert _accept(client, code, F2, status="declined", consent=False).status_code == 200     # открыл и отказался: один
    op(F3); assert _accept(client, code, F3).status_code == 200                                         # открыл и принял с согласием: один
    op(F4); assert _accept(client, code, F4, status="maybe").status_code == 200                         # человек с профилем: не новый
    after = _gm(client)
    d = lambda k: (after[k][0] - before[k][0], after[k][1] - before[k][1])   # noqa: E731
    assert d("acceptance") == (2, 4)                                  # приняли F3, F4 из четверых открывших
    assert d("activation_invited") == (1, 3)                          # новых F1, F2, F3; согласие и решение — у F3
    # ссылка-рекомендация: открытие без согласия тоже считается, повтор и второй человек — нет
    op(F1, ref); op(F5, ref)
    rec = _gm(client)["recommendation"]
    assert rec[0] - before["recommendation"][0] == 1 and rec[1] == before["recommendation"][1]


# ── версия 2: «идёт с тобой» в плане, момент рекомендации и низкая оценка через API, ref-коды без бота ──
def test_plan_shows_companions_for_both_sides(client, db, event):
    code = _create(client, event)["code"]
    services.set_decision(db, INVITER, event, "иду", day=date.fromisoformat(DAY))
    assert _accept(client, code, F1, name="Борис Петров").status_code == 200
    mine = client.get(f"/api/plan/{INVITER}", headers=H, params={"today": DAY}).json()
    theirs = client.get(f"/api/plan/{F1}", headers=H, params={"today": DAY}).json()
    assert mine["days"][DAY][0]["companions"] == ["Борис"] and theirs["days"][DAY][0]["companions"] == ["Аня"]
    assert _notified(db, code) == 1
    client.put(f"/api/profile/{F1}", headers=H, json={"show_name": False})
    mine = client.get(f"/api/plan/{INVITER}", headers=H, params={"today": DAY}).json()
    assert mine["days"][DAY][0]["companions"] == ["другом"]
    _accept(client, code, F2, name="Вера")
    assert client.get(f"/api/plan/{INVITER}", headers=H, params={"today": DAY}).json()["days"][DAY][0]["companions"] == ["другом", "Вера"]


def _rate(client, user, event, n):
    return client.post("/api/decisions", headers=H, json={"user_id": user, "event": event.slug, "status": "went", "rating": n,
                                                          "day": "2026-10-24"})


def test_rating_4_5_gives_ref_ask_once_in_14_days_and_low_rating_asks_reason(client, db, event, monkeypatch):
    from datetime import datetime, timedelta, timezone

    services.set_decision(db, INVITER, event, "иду", day=date(2026, 10, 24))
    r = _rate(client, INVITER, event, 5).json()
    assert r["status"] == "сходил" and r["rating"] == 5 and r["ask_reason"] is False
    assert r["ref_ask"]["url"].startswith("http://localhost:3000/?ref=") and r["ref_ask"]["share_text"].endswith(r["ref_ask"]["url"])
    assert db.scalar(select(GrowthEvent).where(GrowthEvent.user_id == INVITER, GrowthEvent.kind == "ref_ask")) is not None
    assert _rate(client, INVITER, event, 4).json()["ref_ask"] is None                     # снова хорошая оценка: рано
    monkeypatch.setattr(inv_service, "REF_ASK_EVERY", timedelta(seconds=0))
    assert _rate(client, INVITER, event, 5).json()["ref_ask"] is not None                 # прошло 14 дней — снова можно
    assert _rate(client, INVITER, event, 3).json()["ref_ask"] is None
    low = _rate(client, INVITER, event, 2).json()
    assert low["ask_reason"] is True and low["ref_ask"] is None
    r = client.post("/api/decisions", headers=H, json={"user_id": INVITER, "event": event.slug, "status": "went", "rating": 2,
                                                       "reason": "не в это время", "day": "2026-10-24"}).json()
    d = db.scalar(select(Decision).where(Decision.user_id == INVITER))
    db.refresh(d)
    assert d.status == "сходил" and d.rating == 2 and r["status"] == "сходил"
    # «сходил» / «не сходил» раньше дня события нельзя
    assert client.post("/api/decisions", headers=H, json={"user_id": INVITER, "event": event.slug, "status": "skipped",
                                                          "day": "2099-01-01"}).status_code == 400


def test_ref_link_sets_source_via_put_and_consent_counts_as_joined(client, db):
    ref = client.post("/api/invites", headers=H, json={"user_id": INVITER, "kind": "ref"}).json()
    assert ref["url"] == f"http://localhost:3000/?ref={ref['code']}" and ref["web_url"] == ref["url"] and "Попробуй: " in ref["share_text"]
    assert client.post("/api/invites", headers=H, json={"user_id": INVITER, "kind": "ref"}).json()["code"] == ref["code"]
    # человек без согласия: /open профиль не создаёт, источник ставит PUT /api/profile с ref_code
    assert client.post(f"/api/invites/{ref['code']}/open", headers=H, json={"user_id": F1, "name": "Гость"}).status_code == 200
    db.expire_all()
    assert db.get(Profile, F1) is None
    client.put(f"/api/profile/{F1}", headers=H, json={"name": "Гость", "ref_code": ref["code"]})
    db.expire_all()
    p = db.get(Profile, F1)
    assert p.source == "ref" and p.referred_by == INVITER and p.consent_at is None
    inv = db.scalar(select(Invite).where(Invite.code == ref["code"]))
    assert inv.opened == 1 and inv.accepted == 0
    client.put(f"/api/profile/{F1}", headers=H, json={"consent": True})                   # согласие: пришедший по ссылке принят
    db.refresh(inv)
    assert inv.accepted == 1
    client.put(f"/api/profile/{F1}", headers=H, json={"consent": True, "ref_code": ref["code"]})   # повтор не накручивает
    db.refresh(inv)
    assert (inv.opened, inv.accepted) == (1, 1)
    # свой код и чужой формат источник не меняют
    client.put(f"/api/profile/{INVITER}", headers=H, json={"ref_code": ref["code"]})
    client.put(f"/api/profile/{F3}", headers=H, json={"ref_code": "NOSUCH00"})
    db.expire_all()
    assert db.get(Profile, INVITER).source == "organic" and db.get(Profile, F3).source == "organic"
