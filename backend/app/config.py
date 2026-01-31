from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional


class Settings(BaseSettings):
    # App
    app_name: str = "Cold Email Platform"
    debug: bool = False
    log_level: str = "INFO"

    # Database
    database_url: str = "sqlite:///./data/outbound.db"

    # Gmail OAuth
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None
    google_redirect_uri: str = "http://localhost:8000/api/v1/inboxes/oauth/callback"

    # OpenAI
    openai_api_key: Optional[str] = None

    # Security
    secret_key: str = "change-me-in-production"

    # Sending Configuration
    default_daily_limit: int = 20
    min_delay_seconds: int = 30
    max_delay_seconds: int = 90

    # Business Hours (default)
    default_send_start_time: str = "09:00"
    default_send_end_time: str = "17:00"
    default_timezone: str = "America/New_York"

    # Warmup Configuration
    warmup_stage_1_limit: int = 5
    warmup_stage_1_days: int = 7
    warmup_stage_2_limit: int = 10
    warmup_stage_2_days: int = 7
    warmup_stage_3_limit: int = 20
    warmup_stage_3_days: int = 7

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
