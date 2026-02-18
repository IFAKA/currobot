"""Central configuration — all paths via pathlib.Path, no string concatenation."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# Base paths
# ---------------------------------------------------------------------------

ROOT_DIR = Path(__file__).parent.parent          # jobbot/
DATA_DIR = ROOT_DIR / "data"
BACKEND_DIR = ROOT_DIR / "backend"

DB_PATH            = DATA_DIR / "jobs.db"
CV_MASTER_PATH     = DATA_DIR / "cv_master.pdf"
CV_GENERATED_DIR   = DATA_DIR / "cv_generated"
CV_SOURCES_DIR     = DATA_DIR / "cv_sources"
BROWSER_PROFILES_DIR = DATA_DIR / "browser_profiles"
LOGS_DIR           = DATA_DIR / "logs"
BACKUPS_DIR        = DATA_DIR / "backups"
TEMPLATES_DIR      = BACKEND_DIR / "documents" / "templates"

# Ensure directories exist at import time
for _d in (DATA_DIR, CV_GENERATED_DIR, CV_SOURCES_DIR, BROWSER_PROFILES_DIR, LOGS_DIR, BACKUPS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Settings model
# ---------------------------------------------------------------------------

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server
    host: str = "127.0.0.1"
    port: int = 8000
    debug: bool = False

    # Ollama
    ollama_host: str = "http://localhost:11434"
    ollama_timeout: int = 120
    ollama_model: str = ""           # auto-selected at startup if empty
    ollama_model_digest: str = ""    # stored after first pull, verified on startup

    # AI generation params
    cv_rewrite_temperature: float = 0.3
    cv_summary_temperature: float = 0.5
    quality_score_minimum: float = 7.0

    # Scraping
    scraper_default_delay_min: float = 3.0   # seconds
    scraper_default_delay_max: float = 8.0
    scraper_session_max_minutes: int = 45
    scraper_session_max_jobs: int = 50
    scraper_consecutive_zero_disable: int = 2

    # Application flow
    human_review_timeout_minutes: int = 30
    human_review_warn_minutes: int = 25
    submit_confirm_timeout_seconds: int = 10

    # Data retention (days)
    jobs_retention_days: int = 90
    applications_retention_days: int = 365
    logs_retention_days: int = 30
    backups_rolling_days: int = 7

    # First run
    setup_complete: bool = False
    tos_accepted_at: str = ""       # ISO timestamp

    # Feature flags
    sound_enabled: bool = True
    notifications_enabled: bool = True


settings = Settings()


# ---------------------------------------------------------------------------
# Rate limit table (seconds between requests per site)
# ---------------------------------------------------------------------------

RATE_LIMITS: dict[str, tuple[float, float]] = {
    # site_key: (min_delay, max_delay)
    "indeed_es":     (4.0, 9.0),
    "infojobs":      (4.0, 9.0),
    "jobtoday":      (3.0, 7.0),
    "mercadona":     (5.0, 12.0),
    "lidl_es":       (3.0, 7.0),
    "amazon_es":     (6.0, 14.0),
    "manfred":       (3.0, 7.0),
    "tecnoempleo":   (3.0, 7.0),
    "greenhouse":    (2.0, 5.0),
    "lever":         (2.0, 5.0),
    "teamtailor":    (2.0, 5.0),
    "personio":      (2.0, 5.0),
    "workday":       (5.0, 12.0),
    "career_page":   (3.0, 8.0),
}

# Cookie TTL per site (hours)
COOKIE_TTL: dict[str, int] = {
    "indeed_es":  24,
    "infojobs":   48,
    "amazon_es":  12,
    "mercadona":  6,
}

# Max applications per company per N days
COMPANY_APPLICATION_RULES_DEFAULT_DAYS = 14
COMPANY_APPLICATION_RULES_DEFAULT_MAX = 2
