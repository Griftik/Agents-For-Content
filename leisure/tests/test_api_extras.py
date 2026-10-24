"""Просьбы фронтенда к API и боту: решение и ссылки в элементах дайджеста, ручная правка affinity, диплинк /start e_<slug>.

Нужны БД с seed. Тестовые профили (id от pid, tests/ids.py) удаляются после теста.
"""
import os

os.environ.setdefault("ADMIN_PASSWORD", "test-admin")
os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-prod")

import pytest  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

from leisure.api import services  # noqa: E402
from leisure.db.models import Decision, Event, Profile  # noqa: E402
from leisure.db.session import engine, session_factory  # noqa: E402

from .chat import Chat  # noqa: E402
from .ids import user_id  # noqa: E402

API_UID, LINK_UID = user_id(30), user_id(31)
H = {"X-API-Key": "test-key"}
TODAY = {"today": "2026-10-24"}


def _db_ok() -> bool:
    try:
        with engine().connect() as c:
            return c.execute(text("select count(*) from events")).scalar() > 0
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _db_ok(), reason="нет доступной БД с seed")


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from leisure.api.main import app

    with TestClient(app) as c:
        c.delete(f"/api/profile/{API_UID}", headers=H)
        c.put(f"/api/profile/{API_UID}", headers=H, json={"consent": True, "interests": {"Джаз": 3}})
        yield c
        c.delete(f"/api/profile/{API_UID}", headers=H)


@pytest.fixture
def db():
    with session_factory()() as s:
        yield s


# ── 1. решение и ссылки в preview и /all ──
def test_preview_and_all_carry_decision_and_links(client):
    prev = client.get(f"/api/digest/{API_UID}/preview", headers=H, params=TODAY).json()
    first = prev["items"][0]
    assert first["decision"] is None and set(first["links"]) == {"gcal", "outlook", "ics", "tg", "page"} and first["days"]
    slug = first["event"]["slug"]
    client.post("/api/decisions", headers=H, json={"user_id": API_UID, "event": slug, "status": "иду", "day": first["day"]})
    prev = client.get(f"/api/digest/{API_UID}/preview", headers=H, params=TODAY).json()
    mine = next(it for it in prev["items"] + prev["horizon"] if it["event"]["slug"] == slug)
    assert mine["decision"] == {"event_id": first["event"]["id"], "event_slug": slug, "status": "иду", "reason": None,
                                "day": first["day"], "rating": None}
    allv = client.get(f"/api/digest/{API_UID}/all", headers=H, params=TODAY).json()
    row = next(e for e in allv if e["slug"] == slug)
    assert row["decision"]["status"] == "иду" and set(row["links"]) == {"gcal", "outlook", "ics", "tg", "page"}
    others = [e for e in allv if e["slug"] != slug]
    assert all(e["decision"] is None and e["links"]["tg"].startswith("https://t.me/share/url?") for e in others)
    assert all(len(e["links"]["tg"]) <= 1800 for e in allv)


# ── 4. ручная правка affinity ──
def test_manual_affinity_is_validated_stored_and_not_overwritten(client):
    prof = client.get(f"/api/profile/{API_UID}", headers=H).json()
    assert prof["affinity_manual_at"] is None
    for bad in ({"tag": {"неведомый": 1}}, {"cat": {"Не категория": 1}}, {"tag": {"музыка": "много"}},
                {"tag": {"музыка": 1e9}}, {"tag": {"музыка": 1}, "лишнее": {}}, {"tag": [1]}):
        assert client.put(f"/api/profile/{API_UID}", headers=H, json={"affinity": bad}).status_code == 422, bad
    assert client.get(f"/api/profile/{API_UID}", headers=H).json()["affinity_manual_at"] is None

    r = client.put(f"/api/profile/{API_UID}", headers=H, json={"affinity": {"tag": {"музыка": 2.5}, "cat": {"Джаз": -1.0}, "n": 7}})
    assert r.status_code == 200
    p = r.json()
    assert p["affinity"]["tag"]["музыка"] == 2.5 and p["affinity"]["cat"]["Джаз"] == -1.0 and p["affinity_manual_at"]
    assert p["affinity"]["n"] == 0                                          # n считают решения, а не правка

    ev = client.get("/api/events", params=TODAY).json()
    jazz = next(e for e in ev if e["category"] == "Джаз" and "музыка" in e["tags"])
    client.post("/api/decisions", headers=H, json={"user_id": API_UID, "event": jazz["slug"], "status": "иду"})
    aff = client.get(f"/api/profile/{API_UID}", headers=H).json()["affinity"]
    assert aff["n"] == 1 and aff["tag"]["музыка"] == pytest.approx(2.5 + 1.0) and aff["cat"]["Джаз"] == pytest.approx(-1.0 + 1.0)

    client.post("/api/decisions", headers=H, json={"user_id": API_UID, "event": jazz["slug"], "status": "мимо"})
    aff = client.get(f"/api/profile/{API_UID}", headers=H).json()["affinity"]
    assert aff["tag"]["музыка"] == pytest.approx(2.5 - 1.0)               # решение пересчитано, правка осталась поверх


def test_manual_affinity_equal_to_computed_removes_adjustment(db):
    services.delete_profile(db, API_UID)
    p = services.get_or_create_profile(db, API_UID)
    services.update_profile(db, p, {"affinity": {"tag": {"музыка": 3.0}}})
    assert p.affinity["tag"]["музыка"] == 3.0 and p.affinity_manual["tag"] == {"музыка": 3.0}
    services.update_profile(db, p, {"affinity": {"tag": {"музыка": 0.0}}})     # вернули вычисленное (решений нет → 0)
    assert p.affinity_manual["tag"] == {} and p.affinity["tag"].get("музыка", 0) == 0
    services.delete_profile(db, API_UID)


# ── 2. диплинк /start e_<slug> ──
@pytest.fixture
def link(db):
    services.delete_profile(db, LINK_UID)
    ev = db.scalars(select(Event).where(Event.status == "published").order_by(Event.slug).limit(2)).all()[1]
    yield ev
    services.delete_profile(db, LINK_UID)


def test_deeplink_new_user_gets_card_and_setup_offer_and_needs_consent(db, link):
    chat = Chat(LINK_UID)
    chat.say(f"/start e_{link.slug}")
    card, offer = chat.world.chats[LINK_UID][1], chat.world.chats[LINK_UID][2]
    assert card.text.startswith(link.title) and "Совпадение" not in card.text           # профиля нет — оценивать нечем
    assert [b["text"] for r in card.rows[:2] for b in r] == ["Иду", "Может быть", "Интересно", "Мимо"]
    assert offer.text.startswith("Чтобы подборки приходили под тебя, нужна короткая настройка") and "Принять и начать" in [b["text"] for b in offer.buttons()]
    toast = chat.press(card.mid, chat.cbs(card.mid, "Иду"))
    assert toast.startswith("Чтобы сохранить ответ, нужна короткая настройка")
    assert db.scalar(select(Decision).where(Decision.user_id == LINK_UID)) is None     # без согласия ничего не пишем
    chat.press(offer.mid, "ob:consent")                                                  # согласие → решения работают
    assert chat.press(card.mid, chat.cbs(card.mid, "Иду")).startswith("В плане: ")
    assert db.scalar(select(Decision).where(Decision.user_id == LINK_UID)).status == "иду"


def test_deeplink_for_configured_user_is_card_only_with_score(db, link):
    p = services.get_or_create_profile(db, LINK_UID, "Л", "l")
    services.update_profile(db, p, {"consent": True, "onboarded": True})
    chat = Chat(LINK_UID)
    chat.say(f"/start e_{link.slug}")
    msgs = [m for m in chat.world.chats[LINK_UID] if not m.from_user]
    assert len(msgs) == 1 and msgs[0].text.startswith(link.title) and "Совпадение" in msgs[0].text


def test_deeplink_unknown_event_says_so_and_continues_normal_start(db, link):
    chat = Chat(LINK_UID)
    chat.say("/start e_net-takogo-sobytiya")
    texts_ = chat.texts()
    assert texts_[0] == "Этого события уже нет в афише. Подборка на выходные: /digest." and texts_[1].startswith("Я подбираю события")
    chat.say("/start fb_campaign")                                                       # чужой параметр — обычный старт
    assert chat.last_text().startswith("Я подбираю события")
