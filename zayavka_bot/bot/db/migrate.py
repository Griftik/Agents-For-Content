"""Применить миграции alembic до head. Вызывается при старте бота до запуска event loop."""
from __future__ import annotations

from alembic import command
from alembic.config import Config

from bot.config import BASE_DIR


def upgrade_head(url: str) -> None:
    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.attributes["url"] = url
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")
