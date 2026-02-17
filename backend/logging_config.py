"""structlog JSON logging setup — 30-day retention, compress after 7 days."""
from __future__ import annotations

import gzip
import logging
import logging.handlers
import shutil
from datetime import datetime, timezone
from pathlib import Path

import structlog

from backend.config import LOGS_DIR, settings


def setup_logging() -> None:
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_file = LOGS_DIR / f"jobbot-{date_str}.jsonl"

    # Standard library handler → rotating by day
    file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        level=logging.DEBUG,
        handlers=[file_handler, console_handler],
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )

    _prune_old_logs()
    _compress_old_logs()


def _prune_old_logs() -> None:
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc).date()
    for log_path in LOGS_DIR.glob("jobbot-*.jsonl*"):
        try:
            date_part = log_path.name.replace("jobbot-", "").replace(".jsonl", "").replace(".gz", "")
            log_date = datetime.strptime(date_part, "%Y-%m-%d").date()
            age = (cutoff - log_date).days
            if age > settings.logs_retention_days:
                log_path.unlink(missing_ok=True)
        except ValueError:
            pass


def _compress_old_logs() -> None:
    from datetime import timedelta
    cutoff_days = 7
    today = datetime.now(timezone.utc).date()
    for log_path in LOGS_DIR.glob("jobbot-*.jsonl"):
        try:
            date_part = log_path.name.replace("jobbot-", "").replace(".jsonl", "")
            log_date = datetime.strptime(date_part, "%Y-%m-%d").date()
            if (today - log_date).days > cutoff_days:
                gz_path = log_path.with_suffix(".jsonl.gz")
                with log_path.open("rb") as f_in, gzip.open(str(gz_path), "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
                log_path.unlink()
        except ValueError:
            pass
