"""Единый конфиг Фабрики: читает переменные окружения из .env.

Все агенты берут настройки отсюда, а не хардкодят. Секреты живут в .env
на сервере (в git не попадают). Шаблон — .env.example.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Грузим .env из корня проекта, если он есть (на сервере). В git его нет.
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")


def _require(name: str) -> str:
    val = os.getenv(name, "").strip()
    if not val or val == "REPLACE_ME":
        raise RuntimeError(
            f"Не задана обязательная переменная окружения {name}. "
            f"Впиши её в .env на сервере (шаблон — .env.example)."
        )
    return val


def _optional(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


# ─── Секреты (обязательные для запуска агентов) ───
# Читаются лениво через функции, чтобы фундамент импортировался без .env.
def bot_token() -> str:
    return _require("BOT_TOKEN")


def openrouter_key() -> str:
    return _require("OPENROUTER_KEY")


def allowed_user_id() -> int:
    return int(_require("ALLOWED_USER_ID"))


# ─── Необязательные настройки (с разумными значениями по умолчанию) ───
CHANNEL_ID = _optional("CHANNEL_ID", "@neurostrategy")
POST_MODEL = _optional("POST_MODEL", "anthropic/claude-3.5-sonnet")
VOICE_MODEL = _optional("VOICE_MODEL", "openai/whisper-large-v3")

DATA_DIR = Path(_optional("DATA_DIR", str(_ROOT / "data"))).resolve()
DRIVE_REMOTE = _optional("DRIVE_REMOTE", "gdrive")
DRIVE_FOLDER = _optional("DRIVE_FOLDER", "Фабрика пиара")

# Гарантируем, что папка «быстрой» рабочей копии существует.
DATA_DIR.mkdir(parents=True, exist_ok=True)
