"""Интеграционный тест API и админки на реальной БД (DATABASE_URL). Пропускается, если база недоступна.

Использует seed (python -m leisure.seed.load) и отдельного тестового пользователя, которого удаляет после себя.
"""
import os

os.environ.setdefault("ADMIN_PASSWORD", "test-admin")
os.environ.setdefault("API_KEY", "test-key")

import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402

from leisure.db.session import engine, session_factory  # noqa: E402

TEST_USER = 999_000_001


def _db_ok() -> bool:
    try:
        with engine().connect() as c:
            return c.execute(text("select count(*) from events")).scalar() > 0
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _db_ok(), reason="нет доступной БД с seed")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from leisure.api.main import app

    with TestClient(app) as c:
        yield c
    with session_factory()() as s:
        s.execute(text("delete from profiles where user_id = :u"), {"u": TEST_USER})
        s.commit()


H = {"X-API-Key": "test-key"}


def test_health_and_catalog(client):
    assert client.get("/health").json() == {"ok": True}
    cat = client.get("/api/catalog").json()
    assert len(cat["values"]) == 13 and "Джаз" in cat["categories"]


def test_events(client):
    evs = client.get("/api/events", params={"today": "2026-10-24"}).json()
    assert len(evs) >= 100 and all(e["status"] == "published" for e in evs)
    sat = client.get("/api/events", params={"today": "2026-10-24", "day": "2026-10-24", "free": True}).json()
    assert sat and all(e["free"] and "2026-10-24" in e["dates"] for e in sat)
    one = client.get("/api/events/ges2-pocket-ongon-oct24").json()
    assert one["slot"] == "день" and one["free"] is True
    ics = client.get("/api/events/ges2-pocket-ongon-oct24/ics", params={"day": "2026-10-24"})
    assert ics.status_code == 200 and "DTSTART;TZID=Europe/Moscow:20261024T130000" in ics.text
    assert client.get("/api/events/nope").status_code == 404


def test_api_key_required(client):
    assert client.get(f"/api/profile/{TEST_USER}").status_code == 401


def test_profile_digest_decisions_plan(client):
    p = client.get(f"/api/profile/{TEST_USER}", headers=H).json()
    assert p["onboarded"] is False and p["values"]["Творчество"] == 5
    p = client.put(f"/api/profile/{TEST_USER}", headers=H, json={
        "name": "Тест", "values": {"Природа": 5}, "interests": {"Вечеринки": 0}, "params": {"budget": 1500}, "consent": True}).json()
    assert p["onboarded"] is True and p["values"]["Природа"] == 5 and p["interests"]["Вечеринки"] == 0 and p["params"]["budget"] == 1500

    dg = client.get(f"/api/digest/{TEST_USER}/preview", headers=H, params={"today": "2026-10-24"}).json()
    assert dg["title"] == "23–25 октября" and 4 <= len(dg["items"]) <= 5 and len(dg["horizon"]) <= 2
    first = dg["items"][0]
    assert first["links"]["gcal"].startswith("https://calendar.google.com/") and first["event"]["category"] != "Вечеринки"
    assert all(len(it["why"]) <= 4 for it in dg["items"])

    allv = client.get(f"/api/digest/{TEST_USER}/all", headers=H, params={"today": "2026-10-24"}).json()
    assert allv[0]["score"] >= allv[-1]["score"] and len(allv) >= 100

    ev = first["event"]
    d = client.post("/api/decisions", headers=H, json={"user_id": TEST_USER, "event": ev["slug"], "status": "иду", "day": first["day"]}).json()
    assert d["status"] == "иду" and d["event_slug"] == ev["slug"] and d["day"] == first["day"]
    other = dg["items"][1]["event"]
    client.post("/api/decisions", headers=H, json={"user_id": TEST_USER, "event": other["id"], "status": "мимо", "reason": "далеко"})
    decs = client.get(f"/api/decisions/{TEST_USER}", headers=H).json()
    assert {x["status"] for x in decs} == {"иду", "мимо"}
    prof = client.get(f"/api/profile/{TEST_USER}", headers=H).json()
    assert prof["affinity"]["n"] == 2 and prof["affinity"]["cat"].get(ev["category"], 0) > 0

    dg2 = client.get(f"/api/digest/{TEST_USER}/preview", headers=H, params={"today": "2026-10-24"}).json()
    chosen = [it for it in dg2["items"] if it["chosen"]]
    assert chosen and chosen[0]["event"]["slug"] == ev["slug"]
    assert all(it["event"]["id"] != other["id"] for it in dg2["items"])

    plan = client.get(f"/api/plan/{TEST_USER}", headers=H, params={"today": "2026-10-24"}).json()
    assert plan["days"][first["day"]][0]["event"]["slug"] == ev["slug"] and plan["text"].startswith("План на 23–25 октября")

    assert client.delete(f"/api/decisions/{TEST_USER}/{ev['slug']}", headers=H).json() == {"removed": True}
    assert client.post("/api/decisions", headers=H, json={"user_id": TEST_USER, "event": ev["slug"], "status": "хз"}).status_code == 422


def test_admin_login_and_list(client):
    r = client.get("/admin/", follow_redirects=False)
    assert r.status_code in (302, 307)
    r = client.post("/admin/login", data={"username": "admin", "password": "test-admin"}, follow_redirects=False)
    assert r.status_code in (302, 303)
    r = client.get("/admin/event/list")
    assert r.status_code == 200 and "События" in r.text
    r = client.get("/admin/event/create")
    assert r.status_code == 200
    for view in ("profile", "decision", "digest", "organizer"):
        assert client.get(f"/admin/{view}/list").status_code == 200
