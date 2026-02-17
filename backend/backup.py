"""SQLite online backup — startup + after scraper runs. 7 rolling daily backups."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import structlog

from backend.config import BACKUPS_DIR, DB_PATH, settings

log = structlog.get_logger(__name__)


def _backup_filename() -> Path:
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return BACKUPS_DIR / f"jobs-{date_str}.db"


def run_backup() -> Path:
    """Run an online SQLite backup. Safe to call while DB is in use (WAL mode)."""
    dest = _backup_filename()
    try:
        src_conn = sqlite3.connect(str(DB_PATH))
        dst_conn = sqlite3.connect(str(dest))
        with dst_conn:
            src_conn.backup(dst_conn)
        src_conn.close()
        dst_conn.close()
        log.info("backup.completed", dest=str(dest), size_kb=dest.stat().st_size // 1024)
        _prune_old_backups()
        return dest
    except Exception as exc:
        log.error("backup.failed", error=str(exc))
        raise


def _prune_old_backups() -> None:
    """Keep only the N most recent backup files."""
    backups = sorted(BACKUPS_DIR.glob("jobs-*.db"), reverse=True)
    for old in backups[settings.backups_rolling_days:]:
        old.unlink(missing_ok=True)
        log.info("backup.pruned", path=str(old))
