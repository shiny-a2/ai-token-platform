"""Application settings loaded from environment / .env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STORAGE_DIR = BASE_DIR / "storage"
BACKUP_DIR = BASE_DIR / "backups"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram
    bot_token: str = ""
    admin_telegram_id: int = 0
    extra_admin_ids: str = ""

    # OpenAI
    openai_api_key: str = ""
    default_model: str = "gpt-4o-mini"

    # Web admin
    admin_panel_password: str = "change-me-please"
    app_secret: str = "change-me-to-a-long-random-string"
    web_host: str = "0.0.0.0"
    web_port: int = 8095
    # Public base URL of the dashboard (for the /admin button). Optional.
    public_url: str = ""

    @property
    def dashboard_url(self) -> str:
        base = self.public_url.rstrip("/") if self.public_url else f"http://127.0.0.1:{self.web_port}"
        return f"{base}/admin"

    # Economics
    token_unit_price_usd: float = 0.0005
    global_markup_multiplier: float = 1.8
    min_charge_per_request: int = 1
    max_charge_per_request: int = 100_000

    # Misc
    default_language: str = "fa"
    database_url: str = "sqlite+aiosqlite:///./data/app.db"

    @property
    def admin_ids(self) -> set[int]:
        ids: set[int] = set()
        if self.admin_telegram_id:
            ids.add(int(self.admin_telegram_id))
        for chunk in self.extra_admin_ids.split(","):
            chunk = chunk.strip()
            if chunk:
                try:
                    ids.add(int(chunk))
                except ValueError:
                    pass
        return ids

    def is_admin(self, telegram_id: int | None) -> bool:
        return telegram_id is not None and int(telegram_id) in self.admin_ids


@lru_cache
def get_settings() -> Settings:
    for d in (DATA_DIR, STORAGE_DIR, BACKUP_DIR):
        d.mkdir(parents=True, exist_ok=True)
    return Settings()


settings = get_settings()
