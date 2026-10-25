"""Дымовой прогон симулятора приложения (версия 2) отдельным процессом в отдельной базе leisure_sim_smoke: 3 персоны, 1 неделя после недели
онбординга. Проверяет, что люди проходят онбординг через API, открывают ленту, решают и отмечают «сходил», отчёт собирается, а базы
разработки прогон не касается. Пропускается, если нет PostgreSQL с правом CREATEDB."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from leisure import settings

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
            return c.execute(text("select count(*) from profiles where user_id < 999000000")).scalar()   # тестовые id других прогонов не считаем
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
    cmd = [sys.executable, "-m", "leisure.sim.runner", "--users", "3", "--weeks", "1", "--seed", "20261024", "--db-url", url, "--out-dir", str(tmp_path)]
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=240)
    assert r.returncode == 0, (r.stdout[-1500:], r.stderr[-2500:])
    rep = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    md = (tmp_path / "REPORT.md").read_text(encoding="utf-8")
    for h in ("## 1. Метрики п. 11", "## 2. Как люди пользуются приложением", "### Сценарий «освободился вечер»", "### Несколько профилей",
              "### Персональное обучение", "## 3. Дефекты продукта", "## 5. Рост через друзей"):
        assert h in md, h
    ids = {m["id"] for m in rep["spec_metrics"]}
    assert {"activation", "reaction", "plan", "retention", "rating", "growth"} <= ids
    assert rep["meta"]["users"] == 3 and rep["meta"]["weeks"] == 1 and rep["meta"]["product"] == "app-v2"
    m = rep["metrics"]
    assert m["activation"]["completed"] >= 1 and m["opens"]["total"] >= 1 and sum(m["decisions"].values()) >= 1   # онбординг, открытия, решения через API
    assert rep["growth"] and set(rep["growth"]["metrics"]) >= set(("invite_share", "acceptance", "activation_invited", "onboarding_invited", "new_via_friends",
                                                                   "virality", "positive_experience", "recommendation", "together_going"))
    assert rep["vs_previous"] and "closed_defects" in rep
    run = json.loads((tmp_path / "out" / "run_data.json").read_text(encoding="utf-8"))
    assert run["api"]["n_errors"] == 0, run["api"]["errors"]                                   # симуляция не должна ломать продукт
    assert run["db"]["decision_integrity"]["missing"] == 0 and run["db"]["decision_integrity"]["mismatch"] == 0
    assert not {k for k in ("decision_failed", "feed_failed", "plan_failed", "session_failed", "consent_failed", "onboarded_failed") if k in run["findings"]}, run["findings"]
    assert run["scenarios"]["api_probe"]["feed_before_onboarding"]["status"] == 409
    # база симуляции удалена, база разработки не тронута
    assert not _db_exists(SMOKE_DB)
    assert _dev_profiles() == before


def test_personas_are_deterministic():
    from leisure.sim.personas import generate

    a, b = generate(50, 20261024), generate(50, 20261024)
    assert [p.to_dict() for p in a] == [p.to_dict() for p in b]
    assert len(a) == 50 and len({p.idx for p in a}) == 50
