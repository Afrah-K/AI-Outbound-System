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

    # Google Places API (New) key for the Google Maps scraper - can also be
    # saved from the Scrapers page instead
    google_maps_api_key: Optional[str] = None

    # Where the frontend runs - used for links in the reply agent's email alerts
    app_base_url: str = "http://localhost:5173"

    # Security
    secret_key: str = "change-me-in-production"

    # Accounts & sign-in
    # Data from before accounts existed is given to this account on startup
    initial_owner_email: Optional[str] = None
    session_days: int = 30
    session_cookie_name: str = "outbound_session"
    # True when served over HTTPS (deployed) - the cookie is then only sent over HTTPS
    session_cookie_secure: bool = False
    # Google sign-in reuses GOOGLE_CLIENT_ID/SECRET; add this URL to the OAuth client's
    # "Authorized redirect URIs" in Google Cloud Console
    google_login_redirect_uri: str = "http://localhost:8000/api/v1/auth/google/callback"
    # Comma-separated origins allowed to call the API with cookies (the frontend URL(s))
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # Where the schedulers and background jobs run: "in_process" (inside the API -
    # local and Render), "external" (a separate `python -m app.worker` process), or
    # "auto" = external on serverless Vercel, in_process anywhere else
    background_worker: str = "auto"
    # How often the worker looks for newly queued jobs (scrapes, enrichment...).
    # Higher = less CPU on a free plan, at the cost of jobs starting a little later
    job_poll_seconds: float = 1.0

    @property
    def worker_mode(self) -> str:
        import os

        if self.background_worker in ("in_process", "external"):
            return self.background_worker
        return "external" if os.environ.get("VERCEL") else "in_process"

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
