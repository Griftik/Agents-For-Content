from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("CRM_SYNC", "none")

from bot.config import Settings, set_settings  # noqa: E402
from bot.content import load_content, reload_content  # noqa: E402

ADMIN = 1000


@pytest.fixture
def content():
    return load_content(ROOT / "content")


@pytest.fixture
async def db(tmp_path):
    """Чистая SQLite-БД на тест, схема — через те же модели, что и миграция."""
    from bot.db import session as dbs
    from bot.db.models import Base

    url = f"sqlite+aiosqlite:///{tmp_path / 't.db'}"
    set_settings(Settings(
        bot_token="123456:TEST", admin_ids=[ADMIN], database_url=url,
        booking_url="https://example.com/book", privacy_url="https://example.com/privacy",
        consent_url="https://example.com/consent", webapp_url="https://app.example",
        content_dir=ROOT / "content", _env_file=None,
    ))
    reload_content(ROOT / "content")
    engine = dbs.init_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()
