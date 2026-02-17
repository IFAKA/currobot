"""Notifications: events queued in memory, delivered via SSE to the frontend.

The frontend (Tauri) handles displaying native OS notifications using the
tauri-plugin-notification. The backend only queues events.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

_queue: deque[dict] = deque(maxlen=50)


@dataclass
class Notification:
    title: str
    message: str
    sound: Optional[str] = None
    job_id: Optional[int] = None
    application_id: Optional[int] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def send(notif: Notification) -> None:
    _queue.appendleft({
        "title": notif.title,
        "message": notif.message,
        "sound": notif.sound,
        "created_at": notif.created_at.isoformat(),
        "job_id": notif.job_id,
        "application_id": notif.application_id,
    })
    log.info("notification.queued", title=notif.title)


def get_queued() -> list[dict]:
    return list(_queue)


def clear_queued() -> None:
    _queue.clear()


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
        message=f"{site} returned 0 jobs multiple times. Check settings.",
        sound="error",
    ))
