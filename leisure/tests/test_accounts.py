"""Версия 2 (docs/PIVOT-PWA.md): гостевая сессия, несколько профилей на аккаунт, лента по API, план на 7 дней с отметками,
вход по почте. Нужны БД с seed; профили берутся из диапазона tests/ids.py и удаляются после теста."""
import os

os.environ.setdefault("ADMIN_PASSWORD", "test-admin")
os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-prod")

import pytest  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

from leisure import settings  # noqa: E402
from leisure.api import mailer, services  # noqa: E402
from leisure.api.routers import auth as auth_router  # noqa: E402
from leisure.db.models import Account, Decision, EmailToken, Event, Profile  # noqa: E402
from leisure.db.session import engine, session_factory  # noqa: E402

from .ids import user_id  # noqa: E402

A, B = user_id(60), user_id(61)
H = {"X-API-Key": "test-key"}
TODAY = "2026-10-24"
VALUES = {"Творчество": 5, "Красота/эстетика": 5, "Развитие": 5, "Свобода": 5, "Природа": 5}


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
def client(db):
    from fastapi.testclient import TestClient

    from leisure.api.main import app

    created: list[int] = []
    for u in (A, B):
        services.delete_profile(db, u)
    with TestClient(app) as c:
        c.created = created
        yield c
    for u in (A, B, *created):
        services.delete_profile(db, u)
    db.execute(text("delete from accounts where id = any(:ids)"), {"ids": list({A, B, *created})})
    db.commit()


def _onboard(client, uid, **extra):
    return client.put(f"/api/profile/{uid}", headers=H, json={"consent": True, "name": "Я", "values": VALUES, "onboarded": True,
                                                              "interests": {"Джаз": 3}, **extra}).json()


# ── гостевая сессия ──
def test_session_gives_fresh_id_and_stores_nothing_until_consent(client, db):
    r = client.post("/api/session", headers=H)
    assert r.status_code == 200
    uid = r.json()["user_id"]
    client.created.append(uid)
    assert uid >= 10**12 and client.post("/api/session", headers=H).json()["user_id"] > uid
    assert db.get(Profile, uid) is None and db.get(Account, uid) is None                  # до согласия ничего не сохраняется
    assert client.get(f"/api/profile/{uid}", headers=H).status_code == 404
    p = client.put(f"/api/profile/{uid}", headers=H, json={"consent": True, "name": "Гость"}).json()
    assert p["account_id"] == uid and p["kind"] == "self" and p["has_consent"] is True and p["email"] is None
    assert client.post("/api/session").status_code == 401


# ── несколько профилей ──
def test_profiles_per_account_have_own_decisions_feed_and_plan(client, db):
    assert client.post("/api/profiles", headers=H, json={"user_id": A, "name": "Мама", "kind": "parent"}).status_code == 404
    client.put(f"/api/profile/{A}", headers=H, json={"name": "Я"})
    assert client.post("/api/profiles", headers=H, json={"user_id": A, "name": "Мама", "kind": "parent"}).status_code == 409   # нет согласия
    _onboard(client, A)
    r = client.post("/api/profiles", headers=H, json={"user_id": A, "name": "Мама", "kind": "parent"})
    assert r.status_code == 200
    body = r.json()
    assert body["account_id"] == A and [p["kind"] for p in body["profiles"]] == ["self", "parent"]
    mom = next(p for p in body["profiles"] if p["kind"] == "parent")["user_id"]
    client.created.append(mom)
    assert mom != A and not body["profiles"][1]["is_main"] and body["profiles"][0]["is_main"]
    assert client.get("/api/profiles", headers={**H, "X-User-Id": str(mom)}).json()["account_id"] == A   # по любому профилю
    pm = client.get(f"/api/profile/{mom}", headers=H).json()
    assert pm["account_id"] == A and pm["kind"] == "parent" and pm["has_consent"] is True and pm["onboarded"] is False
    assert client.get("/api/feed", headers=H, params={"user_id": mom, "today": TODAY}).status_code == 409   # сначала онбординг
    _onboard(client, mom, values={"Забота": 5, "Семья": 5, "Покой": 5, "Здоровье": 5, "Близость": 5})
    # решения раздельные
    ev = client.get("/api/events", params={"today": TODAY}).json()[0]
    client.post("/api/decisions", headers=H, json={"user_id": mom, "event": ev["slug"], "status": "иду", "day": TODAY})
    assert client.get(f"/api/decisions/{A}", headers=H).json() == [] and len(client.get(f"/api/decisions/{mom}", headers=H).json()) == 1
    assert client.get(f"/api/plan/{mom}", headers=H, params={"today": TODAY}).json()["days"][TODAY][0]["event"]["slug"] == ev["slug"]
    assert client.get(f"/api/plan/{A}", headers=H, params={"today": TODAY}).json()["days"][TODAY] == []
    # лента у каждого своя
    fa = client.get("/api/feed", headers=H, params={"user_id": A, "today": TODAY, "date": "week"}).json()
    fm = client.get("/api/feed", headers=H, params={"user_id": mom, "today": TODAY, "date": "week"}).json()
    assert fa["items"] and fm["items"] and [i["event"]["id"] for i in fa["items"]] != [i["event"]["id"] for i in fm["items"]]
    # основной профиль через /api/profiles не удалить; дополнительный — можно, аккаунт остаётся
    assert client.delete(f"/api/profiles/{A}", headers=H, params={"user_id": mom}).status_code == 400
    assert client.delete(f"/api/profiles/{mom}", headers=H, params={"user_id": B}).status_code == 404       # чужой аккаунт
    assert [p["kind"] for p in client.delete(f"/api/profiles/{mom}", headers=H, params={"user_id": A}).json()["profiles"]] == ["self"]
    db.expire_all()
    assert db.get(Profile, mom) is None and db.scalar(select(Decision).where(Decision.user_id == mom)) is None
    assert db.get(Account, A) is not None
    # удаление основного стирает аккаунт целиком
    mom2 = client.post("/api/profiles", headers=H, json={"user_id": A, "name": "Сын", "kind": "child"}).json()["profiles"][-1]["user_id"]
    client.created.append(mom2)
    assert client.delete(f"/api/profile/{A}", headers=H).json() == {"removed": True}
    db.expire_all()
    assert db.get(Account, A) is None and db.get(Profile, mom2) is None


# ── лента по API ──
def test_feed_api_windows_segments_and_travel_minutes(client, db):
    _onboard(client, A)
    today = client.get("/api/feed", headers=H, params={"user_id": A, "today": TODAY}).json()
    assert today["date"] == "today" and today["days"] == [TODAY] and today["travel_minutes"] == 40 and today["segment"] == "all"
    assert today["items"] and all(it["day"] == TODAY and it["can_make_it"] for it in today["items"])
    assert all(today["items"][i]["score"] >= today["items"][i + 1]["score"] for i in range(len(today["items"]) - 1))
    week = client.get("/api/feed", headers=H, params={"user_id": A, "today": TODAY, "date": "week", "limit": 100}).json()
    assert len(week["days"]) == 7 and len(week["items"]) >= len(today["items"])
    assert client.get("/api/feed", headers=H, params={"user_id": A, "today": TODAY, "date": "tomorrow"}).json()["days"] == ["2026-10-25"]
    assert client.get("/api/feed", headers=H, params={"user_id": A, "today": TODAY, "date": "2026-10-20"}).status_code == 422
    assert client.get("/api/feed", headers=H, params={"user_id": A, "today": TODAY, "segment": "work"}).status_code == 422
    biz = client.get("/api/feed", headers=H, params={"user_id": A, "today": TODAY, "date": "week", "segment": "business"}).json()
    leis = client.get("/api/feed", headers=H, params={"user_id": A, "today": TODAY, "date": "week", "segment": "leisure"}).json()
    from leisure.core.catalog import BUSINESS_CATS
    assert all(it["event"]["category"] in BUSINESS_CATS for it in biz["items"])
    assert all(it["event"]["category"] not in BUSINESS_CATS for it in leis["items"]) and leis["items"]
    # время в пути: в 18:00 с 40 минутами события на 18:30 не успеть, с 5 минутами — успеть
    late = client.get("/api/feed", headers=H, params={"user_id": A, "now": f"{TODAY}T18:00:00", "limit": 100}).json()
    assert late["today"] == TODAY and all(it["can_make_it"] for it in late["items"])
    starts = [it["event"].get("start_time") for it in late["items"] if it["event"].get("kind") not in ("выставка", "место")]
    assert starts and all(s is None or s >= "18:40" for s in starts)                     # выставки и места — пока открыты
    client.put(f"/api/profile/{A}", headers=H, json={"params": {"travel_minutes": 5}})
    close = client.get("/api/feed", headers=H, params={"user_id": A, "now": f"{TODAY}T18:00:00", "limit": 100}).json()
    assert close["travel_minutes"] == 5 and len(close["items"]) >= len(late["items"])
    # «не моё» убирает событие из ленты, «иду» оставляет с decision
    first, second = today["items"][0]["event"], today["items"][1]["event"]
    client.post("/api/decisions", headers=H, json={"user_id": A, "event": first["slug"], "status": "not_mine"})
    client.post("/api/decisions", headers=H, json={"user_id": A, "event": second["slug"], "status": "going", "day": TODAY})
    again = client.get("/api/feed", headers=H, params={"user_id": A, "today": TODAY}).json()
    ids = {it["event"]["id"]: it for it in again["items"]}
    assert first["id"] not in ids and ids[second["id"]]["decision"]["status"] == "иду"
    assert client.get("/api/feed", headers=H, params={"user_id": B, "today": TODAY}).status_code == 404


# ── план: 7 дней, прошедшие с отметками ──
def test_plan_week_window_past_marks_and_rating(client, db):
    """Окно плана 7 дней от «сегодня» (25.10): события 24.10 уже прошедшие, дальше 31.10 — «дальше»."""
    _onboard(client, A)
    today = "2026-10-25"
    pub = select(Event).where(Event.status == "published").order_by(Event.slug)
    past_ev = db.scalars(pub.where(text("dates[array_length(dates, 1)] = '2026-10-24'"))).first()
    far = db.scalars(pub.where(text("dates[1] > '2026-10-31'"))).first()
    soon = db.scalars(pub.where(text("dates @> ARRAY['2026-10-25']::date[]"))).first()
    assert past_ev is not None and far is not None and soon is not None
    far_day = sorted(far.dates)[0].isoformat()
    client.post("/api/decisions", headers=H, json={"user_id": A, "event": past_ev.slug, "status": "иду", "day": "2026-10-24"})
    client.post("/api/decisions", headers=H, json={"user_id": A, "event": far.slug, "status": "может", "day": far_day})
    client.post("/api/decisions", headers=H, json={"user_id": A, "event": soon.slug, "status": "иду", "day": today})
    plan = client.get(f"/api/plan/{A}", headers=H, params={"today": today}).json()
    assert plan["today"] == today and len(plan["weekend"]) == 7 and plan["weekend"][0] == today and plan["weekend"][-1] == "2026-10-31"
    assert plan["days"][today][0]["event"]["slug"] == soon.slug and plan["text"].startswith("План на 25–31 октября")
    assert [h["event"]["slug"] for h in plan["horizon"]] == [far.slug] and plan["horizon"][0]["day"] == far_day
    assert plan["past"][0]["event"]["slug"] == past_ev.slug and plan["past"][0]["status"] == "иду" and plan["past"][0]["rating"] is None
    # отметки «сходил» с оценкой и «не сходил» — только по прошедшим (today передаётся в решение днём события)
    r = client.post("/api/decisions", headers=H, json={"user_id": A, "event": past_ev.slug, "status": "went", "rating": 5})
    assert r.status_code == 200 and r.json()["status"] == "сходил"
    assert client.post("/api/decisions", headers=H, json={"user_id": A, "event": far.slug, "status": "skipped"}).status_code == 400
    plan = client.get(f"/api/plan/{A}", headers=H, params={"today": today}).json()
    assert plan["past"][0]["status"] == "сходил" and plan["past"][0]["rating"] == 5
    prof = client.get(f"/api/profile/{A}", headers=H).json()
    assert prof["affinity"]["cat"].get(past_ev.category, 0) > 1                          # «сходил, 5» усиливает категорию


# ── вход по почте ──
def test_magic_link_503_without_smtp_then_binds_and_moves(client, db, monkeypatch):
    _onboard(client, A)
    monkeypatch.setattr(settings, "SMTP_HOST", "")
    r = client.post("/api/auth/email", headers=H, json={"user_id": A, "email": "a@example.org"})
    assert r.status_code == 503 and r.json()["detail"] == "почта подключится позже"
    assert db.scalar(select(EmailToken)) is None or db.scalar(select(EmailToken).where(EmailToken.account_id == A)) is None
    sent: list[tuple] = []
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.org")
    monkeypatch.setattr(mailer, "send_mail", lambda to, subject, body: sent.append((to, subject, body)))
    assert client.post("/api/auth/email", headers=H, json={"user_id": B, "email": "a@example.org"}).status_code == 409   # без согласия
    assert client.post("/api/auth/email", headers=H, json={"user_id": A, "email": "not-an-email"}).status_code == 422
    r = client.post("/api/auth/email", headers=H, json={"user_id": A, "email": " A@Example.org "})
    assert r.status_code == 200 and r.json()["sent"] is True and len(sent) == 1
    to, _, body = sent[0]
    token = body.split("token=")[1].split()[0]
    assert to == "a@example.org" and token not in body.split("token=")[0]
    assert client.get("/api/auth/email/nope", headers=H).status_code == 404
    c = client.get(f"/api/auth/email/{token}", headers=H).json()
    assert c == {"user_id": A, "account_id": A, "email": "a@example.org", "moved": False}
    assert client.get(f"/api/profile/{A}", headers=H).json()["email"] == "a@example.org"
    assert client.get(f"/api/auth/email/{token}", headers=H).status_code == 410                 # одноразовая
    # другой аккаунт вводит ту же почту: сессию переносят на A
    _onboard(client, B)
    client.post("/api/auth/email", headers=H, json={"user_id": B, "email": "a@example.org"})
    token2 = sent[-1][2].split("token=")[1].split()[0]
    assert client.get(f"/api/auth/email/{token2}", headers=H).json() == {"user_id": A, "account_id": A, "email": "a@example.org", "moved": True}
    assert client.get(f"/api/profile/{B}", headers=H).json()["email"] is None
    # просроченная
    client.post("/api/auth/email", headers=H, json={"user_id": B, "email": "b@example.org"})
    token3 = sent[-1][2].split("token=")[1].split()[0]
    row = db.scalar(select(EmailToken).where(EmailToken.token_hash == auth_router._hash(token3)))
    from datetime import datetime, timedelta, timezone
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    assert client.get(f"/api/auth/email/{token3}", headers=H).status_code == 410
    # лимит писем в час
    for _ in range(5):
        client.post("/api/auth/email", headers=H, json={"user_id": B, "email": "b@example.org"})
    assert client.post("/api/auth/email", headers=H, json={"user_id": B, "email": "b@example.org"}).status_code == 429
