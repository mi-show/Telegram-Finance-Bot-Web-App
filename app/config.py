from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    bot_token: str = Field(..., alias="BOT_TOKEN")
    database_url: str = Field("sqlite+aiosqlite:///./finance.db", alias="DATABASE_URL")
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    date_format: str = Field("%Y-%m-%d", alias="DATE_FORMAT")  # формат даты для парсинга
    max_list_records: int = Field(100, alias="MAX_LIST_RECORDS")  # лимит на выборку
    cache_ttl_seconds: int = Field(300, alias="CACHE_TTL")  # TTL кэша для stats
    webapp_url: str = Field("", alias="WEBAPP_URL")
    webapp_host: str = Field("0.0.0.0", alias="WEBAPP_HOST")
    webapp_port: int = Field(8000, alias="WEBAPP_PORT")
    webapp_init_data_ttl_seconds: int = Field(86400, alias="WEBAPP_INITDATA_TTL")
    webapp_dev_telegram_id: int | None = Field(default=None, alias="WEBAPP_DEV_TELEGRAM_ID")
    recurring_autopost_enabled: bool = Field(True, alias="RECURRING_AUTOPOST_ENABLED")
    recurring_autopost_interval_seconds: int = Field(3600, alias="RECURRING_AUTOPOST_INTERVAL")

    model_config = {
        "env_file": ".env",
        # Support UTF-8 files with/without BOM (common on Windows editors)
        "env_file_encoding": "utf-8-sig",
        "case_sensitive": False,
        "extra": "ignore",  # allow auxiliary vars like postgres_user in .env
    }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]
