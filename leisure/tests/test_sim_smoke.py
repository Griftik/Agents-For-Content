"""Быстрый smoke-тест симулятора пользователей (leisure/sim): 3 персоны, 1 неделя, настоящие обработчики бота и воркера.

Прогон идёт отдельным процессом (симулятор подменяет часы и отправку в процессе, чтобы не влиять на остальные тесты)
и в своей базе leisure_sim_smoke, которую сам создаёт и удаляет. Пропускается, если на сервере нельзя создать базу.
Тесты поддельного Telegram и персон БД не требуют.
"""
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from leisure import settings
from leisure.sim import fakebot, personas

REPO = Path(__file__).resolve().parents[2]
SMOKE_DB = "leisure_sim_smoke"


def _server_url(database: str):
    return make_url(settings.DATABASE_URL).set(database=database)


def _can_create_db() -> bool:
    try:
        eng = create_engine(_server_url("postgres"), connect_args={"connect_timeout": 3})
        with eng.connect() as c:
            return bool(c.execute(text("select rolcreatedb or rolsuper from pg_roles where rolname = current_user")).scalar())
    except Exception:  # noqa: BLE001
        return False


def _dev_profiles() -> int | None:
    try:
        eng = create_engine(make_url(settings.DATABASE_URL), connect_args={"connect_timeout": 3})
        with eng.connect() as c:
            return c.execute(text("select count(*) from profiles")).scalar()
    except Exception:  # noqa: BLE001
        return None


def _db_exists(name: str) -> bool:
    eng = create_engine(_server_url("postgres"), connect_args={"connect_timeout": 3})
    with eng.connect() as c:
        return bool(c.execute(text("select 1 from pg_database where datname = :n"), {"n": name}).scalar())


@pytest.mark.skipif(not _can_create_db(), reason="нет доступа к PostgreSQL с правом CREATEDB")
def test_sim_smoke_three_users_one_week(tmp_path):
    before = _dev_profiles()
    url = _server_url(SMOKE_DB).render_as_string(hide_password=False)
    cmd = [sys.executable, "-m", "leisure.sim.runner", "--users", "3", "--weeks", "1", "--seed", "20261024",
           "--db-url", url, "--out-dir", str(tmp_path), "--no-log"]
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, (r.stdout[-1500:], r.stderr[-2500:])
    rep = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    md = (tmp_path / "REPORT.md").read_text(encoding="utf-8")
    assert "## 1. Метрики п. 11 спеки" in md and "## 3. Дефекты продукта" in md
    ids = {m["id"] for m in rep["spec_metrics"]}
    assert {"activation", "reaction", "plan", "retention", "rating"} <= ids
    assert rep["meta"]["users"] == 3 and rep["meta"]["weeks"] == 1
    # персоны прошли онбординг через бота, подборки дошли и на них нажимали
    assert rep["onboarding"]["completed"] >= 1 and rep["digests"]["sent"] >= 1
    assert rep["decisions"]["total"] >= 1
    assert rep["vs_previous"] and "closed_defects" in rep          # таблица «было → стало» против sim/baseline.json
    assert rep["digests"]["no_interest_button"] is False           # на карточке есть «Интересно» (F6)
    # симуляция не должна ломать продукт: ни исключений в обработчиках, ни потерянных нажатий, ни нарушений формата Bot API
    run = json.loads((tmp_path / "out" / "run_data.json").read_text(encoding="utf-8"))
    assert run["handler_errors"] == 0
    assert run["db"]["decision_integrity"]["missing"] == 0 and run["db"]["decision_integrity"]["mismatch"] == 0
    assert not {k for k in run["violations"] if k not in {"button_url_long", "html_warning"}}, run["violations"]
    # база симуляции удалена, база разработки не тронута
    assert not _db_exists(SMOKE_DB)
    assert _dev_profiles() == before


def test_personas_deterministic_and_diverse():
    a, b = personas.generate(50, 20261024), personas.generate(50, 20261024)
    assert [p.to_dict() for p in a] == [p.to_dict() for p in b]
    assert [p.user_id for p in a] == list(range(900_000_001, 900_000_051))
    assert len({p.archetype for p in a}) >= 8
    assert 0 < sum(1 for p in a if p.abandon_step) < 25            # часть людей отваливается, но не все
    assert all(len(p.top_values) == 5 and len(set(p.top_values)) == 5 for p in a)
    assert [p.to_dict() for p in personas.generate(50, 1)] != [p.to_dict() for p in a]


def test_fake_telegram_enforces_bot_api_rules():
    from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
    from aiogram.types import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup

    world = fakebot.FakeTelegram()
    bot = fakebot.make_bot(world)

    def kb(data="x"):
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="a", callback_data=data)]])

    async def scenario():
        m = await bot.send_message(5, "<b>Привет</b> &lt;", reply_markup=kb())
        assert world.get(5, m.message_id).text == "Привет <"
        await m.edit_reply_markup(reply_markup=kb("y"))
        with pytest.raises(TelegramBadRequest, match="not modified"):
            await m.edit_reply_markup(reply_markup=kb("y"))
        with pytest.raises(TelegramBadRequest):
            await bot.send_message(5, "<b>не закрыт")
        with pytest.raises(TelegramBadRequest):
            await bot.send_message(5, "а < б")
        with pytest.raises(TelegramBadRequest):
            await bot.send_message(5, "ok", reply_markup=kb("z" * 65))
        world.blocked.add(6)
        with pytest.raises(TelegramForbiddenError):
            await bot.send_message(6, "привет")
        upd, cb_id = world.callback_update(bot, 5, "Аня", "anya", m.message_id, "y")
        assert upd.callback_query.message.reply_markup.inline_keyboard[0][0].callback_data == "y"
        await upd.callback_query.answer("ок")
        assert world.callbacks[cb_id]["answered"] and world.callbacks[cb_id]["toast"] == "ок"
        with pytest.raises(TelegramBadRequest):         # повторный ответ на тот же callback Telegram отвергает
            await upd.callback_query.answer("ещё")
        assert await bot.set_my_commands([BotCommand(command="digest", description="Подборка")]) is True
        assert world.commands[-1] == [{"command": "digest", "description": "Подборка"}]

    asyncio.run(scenario())
    assert {v["code"] for v in world.violations} >= {"html_parse", "callback_data_len"}
