import json
import os
from pathlib import Path

# Настройки читаются при первом импорте leisure.settings, поэтому значения для тестов API ставим раньше любых импортов продукта:
# иначе результат зависит от того, какой файл тестов собран первым (отдельный прогон test_api_extras без test_api падал на 503).
os.environ.setdefault("ADMIN_PASSWORD", "test-admin")
os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-prod")

import pytest

from leisure.core.catalog import default_profile
from leisure.normalize.schema import EventIn

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).with_name("fixtures")
WEEKEND = ["2026-10-23", "2026-10-24", "2026-10-25"]


@pytest.fixture(scope="session")
def seed_raw() -> list[dict]:
    return json.loads((ROOT / "seed" / "events_2026-10-23.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def seed_events(seed_raw) -> list[dict]:
    """События seed в формате ядра (id = slug, даты — ISO-строки)."""
    return [EventIn.model_validate(e).as_core() for e in seed_raw]


@pytest.fixture(scope="session")
def by_slug(seed_events) -> dict[str, dict]:
    return {e["slug"]: e for e in seed_events}


@pytest.fixture
def profile() -> dict:
    return default_profile()


@pytest.fixture(scope="session")
def weekend() -> list[str]:
    return WEEKEND


def make_event(**over) -> dict:
    base = {
        "id": "synthetic", "slug": "synthetic", "title": "Синтетическое событие", "category": "Концерты",
        "kind": "событие", "dates": ["2026-10-24"], "time_text": "19:00", "venue": "Зал", "address": "ул. Тестовая, 1",
        "metro": "Тестовая", "price_from": 1000, "price_text": "1 000 ₽", "tags": ["музыка", "камерно", "вечер"],
        "aesthetics": 3, "novelty": 3, "crowd": "камерно", "audience_30plus": True, "url": "https://example.org/e",
        "confidence": "подтверждено", "status": "published",
    }
    base.update(over)
    return base


def fresh_dispatcher():
    """Диспетчер бота для теста. Роутеры модульные и цепляются к одному диспетчеру — отцепляем от прежнего."""
    from leisure.bot import commands, decisions, fallback, onboarding
    from leisure.bot.main import build_dispatcher

    for r in (onboarding.router, decisions.router, commands.router, fallback.router):
        r._parent_router = None
    return build_dispatcher()


@pytest.fixture(scope="session", autouse=True)
def _purge_test_rows():
    """Тестовые профили этого процесса (диапазон tests/ids.py) и служебные события чистятся до сессии и после неё.
    Без доступной БД ничего не делает."""
    import os

    from .ids import RANGE

    def purge():
        try:
            from sqlalchemy import text

            from leisure.db.session import engine

            with engine().begin() as c:
                c.execute(text("delete from profiles where user_id >= :a and user_id < :b"), {"a": RANGE[0], "b": RANGE[1]})
                c.execute(text("delete from events where slug = :s"), {"s": f"zz-test-draft-{os.getpid()}"})
        except Exception:  # noqa: BLE001
            pass

    purge()
    yield
    purge()
