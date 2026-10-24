"""Онбординг v2 (web/FLOW-ONBOARDING.md) через настоящий диспетчер: пути «ничего не меняю» (9 нажатий) и «типичный» (12),
черновик в профиле, режим профиля, меню «Уточнить под себя», /reset. Нужны БД с seed; тестовый профиль 999_100_001."""
import pytest
from sqlalchemy import select, text

from leisure.api import services
from leisure.bot import keyboards as kb
from leisure.core.catalog import ALL_CATS, VALUE_CLUSTERS, VALUES
from leisure.db.models import Digest, Profile
from leisure.db.session import engine, session_factory

from .chat import Chat as _Chat

UID = 999_100_002


def Chat():  # noqa: N802 - свой тестовый пользователь, чтобы не пересекаться с test_defects_db
    return _Chat(UID)


def _db_ok() -> bool:
    try:
        with engine().connect() as c:
            return c.execute(text("select count(*) from events")).scalar() > 0
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _db_ok(), reason="нет доступной БД с seed")
FIVE = ["Творчество", "Развитие", "Дружба", "Эстетика", "Покой"]          # подписи кнопок; «Эстетика» = Красота/эстетика


@pytest.fixture
def db():
    with session_factory()() as s:
        services.delete_profile(s, UID)
        yield s
        services.delete_profile(s, UID)


def _profile(db) -> Profile:
    db.expire_all()
    return db.get(Profile, UID)


def _start_and_pick_five(chat: Chat) -> int:
    chat.say("/start")
    mid = chat.last_mid()
    chat.tap(mid, "Принять и начать")
    for label in FIVE:
        chat.tap(mid, label)
    return mid


def _levels(p: Profile) -> dict[str, int]:
    return {c: int(p.interests[c]) for c in ALL_CATS}


def test_values_screen_has_19_buttons_in_four_clusters():
    rows = kb.values_pick_keyboard([])
    texts = [b["text"] for r in rows[:-1] for b in r]
    assert len(texts) == 19 and rows[-1][0]["text"] == "← Назад" and all(len(r) <= 2 for r in rows)
    assert "Дружба" in texts and "Традиции" in texts and "Эстетика" in texts and "Единство/Дружба" not in texts
    assert sum(len(v) for v in VALUE_CLUSTERS.values()) == 19
    assert len(rows) == 2 + 3 + 4 + 2 + 1                          # ряды групп (4 + 5 + 7 + 3 кнопок по две) и «← Назад»
    five = kb.values_pick_keyboard(VALUES[:5])
    assert five[-2][0] == {"text": "Дальше →", "callback_data": "ob:go:i"} and five[-1][0]["callback_data"] == "ob:go:hi"
    assert all(len(b["callback_data"].encode()) <= 64 for r in five for b in r if "callback_data" in b)


def test_path_nothing_changes_is_9_presses(db):
    chat = Chat()
    mid = _start_and_pick_five(chat)
    assert "Выбрано 5 из 5: Творчество, Дружба, Развитие, Эстетика, Покой. Нажми «Дальше»." in chat.world.get(UID, mid).text
    chat.tap(mid, "Дальше →")
    assert chat.world.get(UID, mid).text.startswith("Шаг 2 из 2 · Интересы")
    p = _profile(db)
    assert p.onboarded_at is None                                   # готов только после подборки
    levels = _levels(p)
    assert sorted(levels.values(), reverse=True)[:6] == [3, 3, 2, 2, 2, 2] and sum(1 for v in levels.values() if v == 1) == 13
    assert not any(v == 0 for v in levels.values())                 # ноль ставит только человек
    assert p.values["Творчество"] == 5 and p.values["Природа"] == 2 and p.params["aesthetics"] is True
    toast = chat.tap(mid, "Показать подборку")
    assert toast == "Собираю подборку." and chat.presses() == 9
    assert chat.world.get(UID, mid).text.startswith("Профиль сохранён.\nГлавные ценности: ")
    assert chat.world.get(UID, mid).rows is None
    p = _profile(db)
    assert p.onboarded_at is not None and p.consent_at is not None
    head = next(m for m in chat.world.chats[UID] if not m.from_user and "вот первая подборка" in m.text)
    assert [b["text"] for b in head.buttons()] == ["Мой план", "Уточнить под себя"]      # localhost: без «Весь дайджест»
    row = db.scalar(select(Digest).where(Digest.user_id == UID))
    assert row is not None and row.sent_at is not None
    assert len(chat.texts()) <= 2 + 7                               # экран онбординга + заголовок и до шести карточек


def test_typical_path_is_12_presses(db):
    chat = Chat()
    mid = _start_and_pick_five(chat)
    chat.tap(mid, "Дальше →")
    shown = [b for r in chat.rows(mid)[:-3] for b in r]
    first = shown[2]                                                # третье из шести — уровень 2 («✓ …»)
    assert first.startswith("✓ ")
    chat.tap(mid, first[2:])                                        # убрал направление (9)
    p = _profile(db)
    removed = [c for c in ALL_CATS if int(p.interests[c]) == 0]
    assert len(removed) == 1
    chat.tap(mid, "Все направления")                                # (10)
    assert chat.world.get(UID, mid).text.startswith("Все направления") and any("● Интересно" == b for r in chat.rows(mid) for b in r)
    other = next(b for r in chat.rows(mid) for b in r if b not in ("● Интересно",) and b.split(" ", 1)[-1] in ALL_CATS + ["Совр. искусство"]
                 and not b.startswith(("✓", "—")))
    chat.tap(mid, other)                                            # добавил направление (11)
    chat.tap(mid, "Показать подборку")                              # (12)
    assert chat.presses() == 12 and _profile(db).onboarded_at is not None


def test_draft_survives_bot_restart_and_brush_sets_level(db):
    chat = Chat()
    mid = _start_and_pick_five(chat)
    chat2 = Chat()                                                  # новый диспетчер = пустая память FSM (перезапуск бота)
    chat2.world, chat2.bot = chat.world, chat.bot
    chat2.tap(mid, "Дальше →")
    assert chat2.world.get(UID, mid).text.startswith("Шаг 2 из 2")
    chat2.tap(mid, "Все направления")
    chat2.tap(mid, "В первую очередь")
    assert "● В первую очередь" in [b for r in chat2.rows(mid) for b in r]
    target = ALL_CATS[0]
    chat2.press(mid, f"ob:cs:0:3")
    assert _profile(db).interests[target] == 3 and "✓✓ Джаз" in [b for r in chat2.rows(mid) for b in r]
    chat2.press(mid, "ob:cs:0:0")
    assert _profile(db).interests[target] == 0 and "— Джаз" in [b for r in chat2.rows(mid) for b in r]


def test_changing_values_recomputes_interests_and_says_so(db):
    chat = Chat()
    mid = _start_and_pick_five(chat)
    chat.tap(mid, "Дальше →")
    chat.tap(mid, "Все направления")
    chat.press(mid, "ob:cs:0:0")                                    # ручная правка
    chat.tap(mid, "← К шести")
    chat.tap(mid, "← Назад")
    assert chat.world.get(UID, mid).text.startswith("Шаг 1 из 2")
    chat.tap(mid, "Покой")                                          # снял Покой
    chat.tap(mid, "Природа")                                        # выбрал Природу
    chat.tap(mid, "Дальше →")
    assert chat.world.get(UID, mid).text.startswith("Ценности изменились, поэтому я заново подобрал направления.")
    assert _profile(db).interests["Джаз"] != 0                       # ручные правки сброшены
    assert chat.tap(mid, "Показать подборку") == "Собираю подборку."


def test_sixth_value_is_refused_and_next_needs_five(db):
    chat = Chat()
    mid = _start_and_pick_five(chat)
    assert chat.tap(mid, "Природа") == "Уже пять. Сними одну, чтобы выбрать другую."
    chat.tap(mid, "Покой")
    assert "Дальше →" not in [b for r in chat.rows(mid) for b in r]
    assert chat.press(mid, "ob:go:i") == "Нужно выбрать ровно пять."  # устаревшая кнопка «Дальше» при четырёх


def test_menu_setup_budget_times_kids_note_and_redo(db):
    chat = Chat()
    mid = _start_and_pick_five(chat)
    chat.tap(mid, "Дальше →")
    chat.tap(mid, "Показать подборку")
    head = next(m for m in chat.world.chats[UID] if not m.from_user and "вот первая подборка" in m.text)
    n_before = len(chat.world.chats[UID])
    chat.press(head.mid, "ob:go:s")                                  # из заголовка — новым сообщением
    menu = chat.last_mid()
    assert menu != head.mid and chat.last_text().startswith("Уточнить под себя") and len(chat.world.chats[UID]) == n_before + 1
    assert "Пересобрать подборку" not in [b for r in chat.rows(menu) for b in r]
    chat.tap(menu, "Бюджет")
    chat.tap(menu, "до 2 500 ₽")
    assert _profile(db).params["budget"] == 2500 and "Бюджет · до 2 500 ₽" in [b for r in chat.rows(menu) for b in r]
    assert "Пересобрать подборку" in [b for r in chat.rows(menu) for b in r]
    chat.tap(menu, "Время")
    chat.tap(menu, "Утро")
    chat.tap(menu, "Ночь")
    assert "✓ Утро" in [b for r in chat.rows(menu) for b in r] and "Готово" in [b for r in chat.rows(menu) for b in r]
    chat.tap(menu, "Готово")
    assert _profile(db).params["times"] == ["утро", "день", "вечер", "ночь"]
    chat.tap(menu, "С детьми")
    chat.tap(menu, "Да, с детьми")
    p = _profile(db)
    assert p.params["company"] == "с детьми" and p.params["kids"] is True
    chat.tap(menu, "Заметка")
    assert chat.world.get(UID, menu).text.startswith("Что надоело и что хочется попробовать")
    chat.say("Надоели бары, хочу в стеклодувную мастерскую")
    assert "Записал в профиль." in chat.texts()[-2] and chat.last_text().startswith("Уточнить под себя")
    assert _profile(db).notes.startswith("Надоели бары") and chat.state() is None
    new_menu = chat.last_mid()
    assert "Заметка · есть" in [b for r in chat.rows(new_menu) for b in r]
    before = len(chat.world.chats[UID])
    assert chat.tap(new_menu, "Пересобрать подборку") == "Собираю подборку."
    assert len(chat.world.chats[UID]) > before + 1                    # пришла подборка
    chat.tap(new_menu, "Готово")
    assert chat.world.get(UID, new_menu).text == "Сохранил. Поменять ответы можно в любой момент: /profile."


def test_profile_mode_saves_without_new_digest(db):
    chat = Chat()
    mid = _start_and_pick_five(chat)
    chat.tap(mid, "Дальше →")
    chat.tap(mid, "Показать подборку")
    n = len(chat.world.chats[UID])
    chat.say("/profile")
    pm = chat.last_mid()
    assert chat.last_text().startswith("Твой профиль\n\nГлавные ценности\n")
    assert [[b for b in r] for r in chat.rows(pm)] == [["Ценности", "Интересы"], ["Бюджет, эстетика, время", "Заметка"]]
    chat.tap(pm, "Интересы")
    assert chat.world.get(UID, pm).text.startswith("Шаг 2 из 2") and "Сохранить" in [b for r in chat.rows(pm) for b in r]
    chat.press(pm, "ob:ct:0")
    chat.tap(pm, "Сохранить")
    assert chat.world.get(UID, pm).text == "Сохранил. Новая подборка придёт в четверг, а сейчас её можно собрать: /digest."
    assert len(chat.world.chats[UID]) == n + 2                        # только «/profile» и ответ: новая подборка не пришла


def test_reset_keeps_consent_and_sends_regular_digest(db):
    chat = Chat()
    mid = _start_and_pick_five(chat)
    chat.tap(mid, "Дальше →")
    chat.tap(mid, "Показать подборку")
    chat.say("/reset")
    assert chat.last_text().startswith("Настроим заново. Новые ответы заменят прежние, а решения по событиям останутся.")
    rmid = chat.last_mid()
    assert "Принять и начать" not in [b for r in chat.rows(rmid) for b in r] and "✓ Творчество" in [b for r in chat.rows(rmid) for b in r]
    chat.tap(rmid, "Дальше →")
    chat.tap(rmid, "Показать подборку")
    assert any("подобрал" in t for t in chat.texts()[-8:])
    assert _profile(db).consent_at is not None


def test_start_again_and_resume(db):
    chat = Chat()
    chat.say("/start")
    chat.tap(chat.last_mid(), "Принять и начать")
    chat.say("/start")                                               # согласие дано, ценностей нет — снова Э1
    assert chat.last_text().startswith("Шаг 1 из 2")
    mid = chat.last_mid()
    for label in FIVE:
        chat.tap(mid, label)
    chat.say("/start")                                               # ценности есть — Э2
    assert chat.last_text().startswith("Шаг 2 из 2")
    chat.tap(chat.last_mid(), "Показать подборку")
    chat.say("/start")
    assert chat.last_text() == "Профиль уже настроен. Подборка на эти выходные: /digest. Твой план: /plan. Поменять ответы: /profile."


def test_text_on_values_step_gets_hint_and_keeps_screen(db):
    chat = Chat()
    chat.say("/start")
    mid = chat.last_mid()
    chat.tap(mid, "Принять и начать")
    chat.say("а что тут нужно сделать?")
    assert chat.last_text().startswith("Здесь нужно нажать кнопку под сообщением")
    assert chat.world.get(UID, mid).text.startswith("Шаг 1 из 2")
