"""Platform-abstracted notifications: macOS → plyer → fallback queue."""
from __future__ import annotations

import asyncio
import platform
import subprocess
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

_OS = platform.system()  # "Darwin" | "Windows" | "Linux"

# In-memory fallback queue (shown in dashboard if native notifications unavailable)
_fallback_queue: deque[dict] = deque(maxlen=50)


@dataclass
class Notification:
    title: str
    message: str
    sound: Optional[str] = None          # maps to sounds.ts keys
    job_id: Optional[int] = None
    application_id: Optional[int] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def send(notif: Notification) -> None:
    """Fire notification — tries native first, falls back to queue."""
    try:
        if _OS == "Darwin":
            _send_macos(notif)
        else:
            _send_plyer(notif)
    except Exception as exc:
        log.warning("notification.native_failed", error=str(exc))
        _fallback_queue.appendleft({
            "title": notif.title,
            "message": notif.message,
            "created_at": notif.created_at.isoformat(),
            "job_id": notif.job_id,
        })


def get_queued() -> list[dict]:
    return list(_fallback_queue)


def clear_queued() -> None:
    _fallback_queue.clear()


# ---------------------------------------------------------------------------
# Platform implementations
# ---------------------------------------------------------------------------

def _send_macos(notif: Notification) -> None:
    script = (
        f'display notification "{notif.message}" '
        f'with title "JobBot" subtitle "{notif.title}"'
    )
    subprocess.run(["osascript", "-e", script], check=True, capture_output=True)
    log.info("notification.sent", platform="macos", title=notif.title)


def _send_plyer(notif: Notification) -> None:
    try:
        from plyer import notification as plyer_notif
        plyer_notif.notify(
            title=f"JobBot — {notif.title}",
            message=notif.message,
            app_name="JobBot",
            timeout=5,
        )
        log.info("notification.sent", platform="plyer", title=notif.title)
    except Exception as exc:
        raise RuntimeError(f"plyer failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def notify_review_ready(job_id: int, company: str, title: str) -> None:
    send(Notification(
        title="Review Required",
        message=f"{company} — {title}",
        sound="notification",
        job_id=job_id,
    ))


def notify_applied(job_id: int, company: str, title: str) -> None:
    send(Notification(
        title="Application Submitted",
        message=f"✓ {company} — {title}",
        sound="success",
        job_id=job_id,
    ))


def notify_session_expiring(job_id: int, minutes_remaining: int) -> None:
    send(Notification(
        title="Session Expiring",
        message=f"Form session expires in {minutes_remaining} minutes. Review now.",
        sound="error",
        job_id=job_id,
    ))


def notify_scraper_disabled(site: str) -> None:
    send(Notification(
        title="Scraper Disabled",
        message=f"{site} returned 0 jobs multiple times. Check in settings.",
        sound="error",
    ))
