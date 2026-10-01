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
    bot_name: str = "GrigorevStratagy_bot"
    owner_name: str = "Евгений Григорьев"
    channel_username: str = "neurostrategy"
    admin_ids: list[int] = Field(default_factory=lambda: [291136301])

    database_url: str = f"sqlite+aiosqlite:///{BASE_DIR / 'storage' / 'bot.db'}"

    booking_mode: str = "url"  # url | slots (slots — полная версия)
    booking_url: str = "https://calendly.com/egrigorev/30min"
    privacy_url: str = "https://telegra.ph/Politika-obrabotki-personalnyh-dannyh-09-30-7"
    consent_url: str = "https://telegra.ph/Soglasie-na-obrabotku-personalnyh-dannyh-09-30-113"  # отдельный документ согласия (152-ФЗ с 01.09.2025), ссылается на политику

    crm_sync: CrmSync = CrmSync.none
    google_service_account_json: Path | None = None
    google_sheet_id: str = ""
    google_sheet_tab: str = "leads"
    amocrm_webhook_url: str = ""

    # Мини-приложение: адрес https (без домена — <ip-через-дефисы>.sslip.io, ставит установщик)
    webapp_url: str = ""
    webapp_port: int = 8080
    initdata_max_age_sec: int = 24 * 3600

    # Важное из канала: бот — админ канала, пост с этим тегом предлагается к рассылке
    digest_tag: str = "#важное"

    # Платная подписка на бизнес-аналитику (цена и тексты — content/subscription.yaml)
    payment_provider_token: str = ""  # ЮKassa через @BotFather → Payments; пусто — оплата в Stars
    payment_receipts: bool = True     # чек по 54-ФЗ через ЮKassa (email покупателя уходит в ЮKassa)
    payment_vat_code: int = 1         # 1 — без НДС (самозанятый / УСН)
    offer_url: str = ""               # публичная оферта на подписку

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
