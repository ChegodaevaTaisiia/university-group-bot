"""Конфигурация бота: читается из окружения / .env один раз при старте."""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import (
    BaseSettings,
    NoDecode,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # .env важнее переменных окружения ОС: у пользователя может быть глобально
        # задан ANTHROPIC_BASE_URL / ANTHROPIC_API_KEY для других проектов.
        # В Docker .env-файла внутри контейнера нет → работает env_settings.
        return init_settings, dotenv_settings, env_settings, file_secret_settings

    # Telegram
    bot_token: str
    admin_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)
    supergroup_id: int | None = None

    # Локаль / время
    timezone: str = "Europe/Moscow"
    semester_start: date = date(2026, 9, 1)
    greetings_hour: int = 9  # во сколько поздравлять с ДР и праздниками
    bot_nickname: str = "Биби"  # обращение к боту в чате: «Биби, что задали?»

    # Хранилище
    data_dir: Path = Path("./data")

    # ИИ
    anthropic_api_key: str | None = None
    # Свой endpoint (если ключ от прокси, а не прямой от Anthropic). Пусто = api.anthropic.com
    anthropic_base_url: str | None = None
    ai_model: str = "claude-haiku-4-5"
    ai_monthly_budget_usd: float = 5.0
    ai_user_hourly_limit: int = 15

    # База знаний: страница твоей высшей школы / факультета на сайте вуза
    kb_school_url: str | None = (
        "https://www.rea.ru/structure/hs/vyisshaya-shkola-kibertehnologiy-matematiki-i-statistiki"
    )

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _split_admin_ids(cls, v: object) -> object:
        if isinstance(v, str):
            return [int(x) for x in v.replace(";", ",").split(",") if x.strip()]
        if isinstance(v, int):
            return [v]
        return v

    @field_validator(
        "supergroup_id", "anthropic_api_key", "anthropic_base_url", "kb_school_url", mode="before"
    )
    @classmethod
    def _blank_to_none(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "bot.sqlite"

    @property
    def db_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.db_path.as_posix()}"

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    @property
    def ai_enabled(self) -> bool:
        return bool(self.anthropic_api_key)

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.files_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
