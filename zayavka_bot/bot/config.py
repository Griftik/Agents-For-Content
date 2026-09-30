"""Конфиг из .env (pydantic-settings). Параметры блока «0. Параметры» ТЗ."""
from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class CrmSync(str, Enum):
    none = "none"
    google_sheets = "google_sheets"
    amocrm_webhook = "amocrm_webhook"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    bot_token: str = Field(..., description="токен от @BotFather")
    bot_name: str = "strategy_diag_bot"
    owner_name: str = "Евгений Григорьев"
    channel_username: str = "neurostrategy"
    admin_ids: list[int] = Field(default_factory=list)

    database_url: str = f"sqlite+aiosqlite:///{BASE_DIR / 'storage' / 'bot.db'}"

    booking_mode: str = "url"  # url | slots (slots — полная версия)
    booking_url: str = ""
    privacy_url: str = ""

    crm_sync: CrmSync = CrmSync.none
    google_service_account_json: Path | None = None
    google_sheet_id: str = ""
    google_sheet_tab: str = "leads"
    amocrm_webhook_url: str = ""

    contact_timeout_min: int = 10  # через сколько минут без телефона заявка уходит без него
    content_dir: Path = BASE_DIR / "content"
    prompts_dir: Path = BASE_DIR / "prompts"
    log_level: str = "INFO"
    log_json: bool = True

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _parse_ids(cls, v):
        # ADMIN_IDS=123,456 или [123, 456]
        if isinstance(v, str):
            v = v.strip().strip("[]")
            return [int(x) for x in v.replace(";", ",").split(",") if x.strip()]
        if isinstance(v, int):
            return [v]
        return v

    @property
    def channel_url(self) -> str:
        return f"https://t.me/{self.channel_username}"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings


def set_settings(s: Settings) -> None:
    """Для тестов."""
    global _settings
    _settings = s
