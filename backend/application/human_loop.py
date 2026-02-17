"""Human-in-the-loop review and authorized submission flow."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import CV_GENERATED_DIR, settings
from backend.database.models import Application, ApplicationStatus

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Timeout tracking (application_id → asyncio.Task)
# ---------------------------------------------------------------------------
_timeout_tasks: dict[int, asyncio.Task] = {}


# ---------------------------------------------------------------------------
# prepare_for_review
# ---------------------------------------------------------------------------

async def prepare_for_review(
    db: AsyncSession,
    application_id: int,
    page: Any,
) -> None:
    """
    Serialize form state and transition to pending_human_review.

    Steps:
        1. Take full-page screenshot of the filled form.
        2. Serialize ALL current field values to application.form_fields_json.
        3. Store the current URL as application.form_url.
        4. Transition application to pending_human_review.
        5. Start 30-minute timeout task.
        6. Fire notification: notify_review_ready.
        7. Broadcast SSE: review_ready event.
    """
    from backend.database.crud import get_application, transition_application

    app = await get_application(db, application_id)
    if not app:
        log.error("human_loop.prepare.app_not_found", application_id=application_id)
        return

    # ------------------------------------------------------------------
    # Step 1: Screenshot of the filled form
    # ------------------------------------------------------------------
    out_dir = CV_GENERATED_DIR / str(application_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = str(out_dir / "form.png")

    try:
        await page.screenshot(path=screenshot_path, full_page=True)
        log.info(
            "human_loop.screenshot_taken",
            path=screenshot_path,
            application_id=application_id,
        )
    except Exception as e:
        log.warning(
            "human_loop.screenshot_failed",
            error=str(e),
            application_id=application_id,
        )

    # ------------------------------------------------------------------
    # Step 2: Serialize all field values from the page
    # ------------------------------------------------------------------
    form_fields: dict = {}
    try:
        form_fields = await page.evaluate(_JS_SERIALIZE_FIELDS)
        log.info(
            "human_loop.fields_serialized",
            field_count=len(form_fields),
            application_id=application_id,
        )
    except Exception as e:
        log.warning(
            "human_loop.serialize_failed",
            error=str(e),
            application_id=application_id,
        )

    # ------------------------------------------------------------------
    # Step 3: Store form URL
    # ------------------------------------------------------------------
    form_url = page.url

    # ------------------------------------------------------------------
    # Step 4: Transition to pending_human_review
    # ------------------------------------------------------------------
    await transition_application(
        db,
        app,
        ApplicationStatus.pending_human_review,
        triggered_by="human_loop",
        note=f"Form ready for review at {form_url}",
        form_screenshot_path=screenshot_path,
        form_fields_json=form_fields,
        form_url=form_url,
    )

    # ------------------------------------------------------------------
    # Step 5: Start timeout task
    # ------------------------------------------------------------------
    if application_id in _timeout_tasks:
        _timeout_tasks[application_id].cancel()

    task = asyncio.create_task(
        handle_session_timeout(application_id),
        name=f"human_loop_timeout_{application_id}",
    )
    _timeout_tasks[application_id] = task

    # ------------------------------------------------------------------
    # Step 6 & 7: Notifications and SSE
    # ------------------------------------------------------------------
    company = app.company
    title = _get_job_title(app)

    await _notify_review_ready(application_id, company, title)
    await _broadcast_sse_review_ready(application_id, company, title, form_url, screenshot_path)

    log.info(
        "human_loop.prepare_complete",
        application_id=application_id,
        company=company,
        form_url=form_url,
    )


# ---------------------------------------------------------------------------
# submit_authorized
# ---------------------------------------------------------------------------

async def submit_authorized(
    db: AsyncSession,
    application_id: int,
) -> dict:
    """
    Execute authorized submission using serialized form data.

    Steps:
        1. Load application from DB.
        2. Validate session not expired (updated_at + 30 min).
        3. Create browser context, navigate to form_url.
        4. Re-fill form fields from form_fields_json.
        5. Verify fields match serialized values.
        6. Find and click submit button.
        7. Run confirm_detector.
        8. Update application status.
        9. Store confirmation screenshot path.
        10. Log authorization event.

    Returns:
        {"status": "applied" | "submitted_ambiguous" | "expired"}
    """
    from backend.database.crud import get_application, transition_application

    app = await get_application(db, application_id)
    if not app:
        log.error("human_loop.submit.app_not_found", application_id=application_id)
        return {"status": "error", "detail": "Application not found"}

    # ------------------------------------------------------------------
    # Step 2: Check session expiry
    # ------------------------------------------------------------------
    if _is_session_expired(app):
        log.warning(
            "human_loop.submit.session_expired",
            application_id=application_id,
            updated_at=app.updated_at,
        )
        return {"status": "expired"}

    if not app.form_url or not app.form_fields_json:
        log.error(
            "human_loop.submit.missing_form_data",
            application_id=application_id,
            has_url=bool(app.form_url),
            has_fields=bool(app.form_fields_json),
        )
        return {"status": "error", "detail": "Form data missing"}

    # ------------------------------------------------------------------
    # Step 3: Create browser context and navigate
    # ------------------------------------------------------------------
    from playwright.async_api import async_playwright  # type: ignore

    from backend.application.confirm_detector import detect_confirmation

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )
            page = await context.new_page()

            try:
                log.info(
                    "human_loop.submit.navigating",
                    url=app.form_url,
                    application_id=application_id,
                )
                await page.goto(app.form_url, wait_until="networkidle", timeout=30000)

                # ----------------------------------------------------------
                # Step 4: Re-fill form fields (fast, no human simulation)
                # ----------------------------------------------------------
                filled_count = await _refill_form_fast(page, app.form_fields_json)
                log.info(
                    "human_loop.submit.refilled",
                    filled_count=filled_count,
                    application_id=application_id,
                )

                # ----------------------------------------------------------
                # Step 5: Verify field values match serialized snapshot
                # ----------------------------------------------------------
                mismatches = await _verify_fields(page, app.form_fields_json)
                if mismatches:
                    log.warning(
                        "human_loop.submit.field_mismatch",
                        mismatches=mismatches,
                        application_id=application_id,
                    )

                # ----------------------------------------------------------
                # Step 6: Find and click submit button
                # ----------------------------------------------------------
                clicked = await _click_submit(page)
                if not clicked:
                    log.error(
                        "human_loop.submit.no_submit_button",
                        application_id=application_id,
                        url=page.url,
                    )
                    await browser.close()
                    return {"status": "error", "detail": "Submit button not found"}

                # ----------------------------------------------------------
                # Step 7: Detect confirmation
                # ----------------------------------------------------------
                confirmation = await detect_confirmation(
                    page,
                    application_id,
                    timeout_seconds=settings.submit_confirm_timeout_seconds,
                )

                # ----------------------------------------------------------
                # Step 8 & 9: Update application status
                # ----------------------------------------------------------
                status_map = {
                    True: ApplicationStatus.applied,
                    False: ApplicationStatus.submitted_ambiguous,
                }
                new_status = (
                    ApplicationStatus.applied
                    if confirmation["confirmed"]
                    else ApplicationStatus.submitted_ambiguous
                )

                await transition_application(
                    db,
                    app,
                    new_status,
                    triggered_by="human_loop.submit_authorized",
                    note=(
                        f"Signal: {confirmation['signal']}. "
                        f"Authorized by human at {datetime.now(timezone.utc).isoformat()}"
                    ),
                    confirmation_screenshot_path=confirmation.get("screenshot_path", ""),
                    confirmation_signal=confirmation["signal"],
                    authorized_by_human=True,
                    authorized_at=datetime.now(timezone.utc),
                )

                # ----------------------------------------------------------
                # Step 10: Log authorization event
                # ----------------------------------------------------------
                log.info(
                    "human_loop.submit.authorized_event",
                    application_id=application_id,
                    status=new_status.value,
                    signal=confirmation["signal"],
                    confirmed=confirmation["confirmed"],
                )

                # Cancel timeout task
                _cancel_timeout_task(application_id)

                final_status = "applied" if confirmation["confirmed"] else "submitted_ambiguous"
                return {
                    "status": final_status,
                    "signal": confirmation["signal"],
                    "screenshot_path": confirmation.get("screenshot_path", ""),
                }

            finally:
                await browser.close()

    except Exception as e:
        log.error(
            "human_loop.submit.error",
            error=str(e),
            application_id=application_id,
        )
        return {"status": "error", "detail": str(e)}


# ---------------------------------------------------------------------------
# Session timeout handler
# ---------------------------------------------------------------------------

async def handle_session_timeout(application_id: int) -> None:
    """
    Handle the 30-minute human review session timeout.

    At 25 minutes: send expiry warning notification.
    At 30 minutes: log warning, keep status as pending_human_review.
    """
    warn_seconds = settings.human_review_warn_minutes * 60
    timeout_seconds = settings.human_review_timeout_minutes * 60

    log.info(
        "human_loop.timeout_task.started",
        application_id=application_id,
        timeout_minutes=settings.human_review_timeout_minutes,
    )

    try:
        # Wait until 25-minute warning
        await asyncio.sleep(warn_seconds)
        remaining_minutes = settings.human_review_timeout_minutes - settings.human_review_warn_minutes

        log.info(
            "human_loop.timeout_task.warning",
            application_id=application_id,
            remaining_minutes=remaining_minutes,
        )
        await _notify_session_expiring(application_id, remaining_minutes)

        # Wait remaining time until full timeout
        await asyncio.sleep(timeout_seconds - warn_seconds)

        log.warning(
            "human_loop.timeout_task.expired",
            application_id=application_id,
            timeout_minutes=settings.human_review_timeout_minutes,
        )
        # Status remains pending_human_review — operator must decide
        # Release any held browser resources
        _cancel_timeout_task(application_id)

    except asyncio.CancelledError:
        log.info(
            "human_loop.timeout_task.cancelled",
            application_id=application_id,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_session_expired(app: Application) -> bool:
    """Check whether the 30-minute review window has elapsed."""
    if not app.updated_at:
        return False
    # Make updated_at timezone-aware if it's naive
    updated = app.updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    expiry = updated + timedelta(minutes=settings.human_review_timeout_minutes)
    return datetime.now(timezone.utc) > expiry


def _get_job_title(app: Application) -> str:
    """Extract job title from application relationships (best effort)."""
    try:
        if hasattr(app, "job") and app.job:
            return app.job.title or app.cv_profile
    except Exception:
        pass
    return app.cv_profile


async def _notify_review_ready(
    application_id: int,
    company: str,
    title: str,
) -> None:
    """Fire notification that a CV is ready for human review."""
    try:
        from backend.notifications import notify_review_ready  # type: ignore
        await notify_review_ready(application_id, company, title)
    except ImportError:
        log.debug(
            "human_loop.notify.module_not_found",
            notification="notify_review_ready",
        )
    except Exception as e:
        log.warning("human_loop.notify.failed", error=str(e))


async def _broadcast_sse_review_ready(
    application_id: int,
    company: str,
    title: str,
    form_url: str,
    screenshot_path: str,
) -> None:
    """Broadcast SSE event for the dashboard."""
    try:
        from backend.api.sse import sse_hub  # type: ignore
        await sse_hub.broadcast(
            "review_ready",
            {
                "application_id": application_id,
                "company": company,
                "title": title,
                "form_url": form_url,
                "screenshot_path": screenshot_path,
                "expires_at": (
                    datetime.now(timezone.utc)
                    + timedelta(minutes=settings.human_review_timeout_minutes)
                ).isoformat(),
            },
        )
    except ImportError:
        log.debug("human_loop.sse.module_not_found")
    except Exception as e:
        log.warning("human_loop.sse.broadcast_failed", error=str(e))


async def _notify_session_expiring(application_id: int, minutes_remaining: int) -> None:
    """Warn human that review session is about to expire."""
    try:
        from backend.notifications import notify_session_expiring  # type: ignore
        await notify_session_expiring(application_id, minutes_remaining)
    except ImportError:
        log.debug("human_loop.notify.module_not_found", notification="notify_session_expiring")
    except Exception as e:
        log.warning("human_loop.notify_expiring.failed", error=str(e))

    try:
        from backend.api.sse import sse_hub  # type: ignore
        await sse_hub.broadcast(
            "review_expiring",
            {
                "application_id": application_id,
                "minutes_remaining": minutes_remaining,
            },
        )
    except Exception:
        pass


async def _refill_form_fast(page: Any, form_fields_json: dict) -> int:
    """
    Re-fill form fields from serialized snapshot (fast, no human delays).
    Returns count of successfully filled fields.
    """
    filled = 0
    for ref, value in form_fields_json.items():
        if not ref or not value:
            continue
        try:
            tag = await page.evaluate(
                f"(ref) => {{ const el = document.querySelector(ref); return el ? el.tagName.toLowerCase() : null; }}",
                ref,
            )
            if not tag:
                continue

            if tag in ("input", "textarea"):
                field_type = await page.evaluate(
                    f"(ref) => {{ const el = document.querySelector(ref); return el ? (el.type || 'text').toLowerCase() : 'text'; }}",
                    ref,
                )
                if field_type == "file":
                    if Path(str(value)).exists():
                        await page.set_input_files(ref, str(value))
                        filled += 1
                elif field_type == "checkbox":
                    current = await page.is_checked(ref)
                    should_check = bool(value)
                    if current != should_check:
                        await page.click(ref)
                    filled += 1
                else:
                    await page.fill(ref, str(value))
                    filled += 1
            elif tag == "select":
                await page.select_option(ref, str(value))
                filled += 1

        except Exception as e:
            log.debug(
                "human_loop.refill.field_failed",
                ref=ref,
                error=str(e),
            )

    return filled


async def _verify_fields(page: Any, expected: dict) -> list[dict]:
    """
    Compare current field values against the serialized snapshot.
    Returns list of mismatches.
    """
    mismatches: list[dict] = []
    for ref, expected_value in expected.items():
        if not ref:
            continue
        try:
            actual = await page.evaluate(
                f"(ref) => {{ const el = document.querySelector(ref); return el ? el.value : null; }}",
                ref,
            )
            if actual is None:
                continue
            if str(actual).strip() != str(expected_value).strip():
                mismatches.append({
                    "ref": ref,
                    "expected": str(expected_value)[:50],
                    "actual": str(actual)[:50],
                })
        except Exception:
            pass
    return mismatches


async def _click_submit(page: Any) -> bool:
    """
    Find and click the submit button using multiple selectors.
    Returns True if a submit button was found and clicked.
    """
    selectors = [
        "button[type='submit']",
        "input[type='submit']",
        "button:has-text('enviar')",
        "button:has-text('Enviar')",
        "button:has-text('aplicar')",
        "button:has-text('Aplicar')",
        "button:has-text('submit')",
        "button:has-text('Submit')",
        "button:has-text('apply')",
        "button:has-text('Apply')",
        "button:has-text('solicitar')",
        "button:has-text('Solicitar')",
        "button:has-text('inscribirme')",
        "button:has-text('Inscribirme')",
        "button:has-text('enviar solicitud')",
        "button:has-text('Enviar solicitud')",
        "[data-testid='submit']",
        "[data-testid='apply']",
        ".submit-btn",
        ".apply-btn",
        "#submit",
        "#apply",
    ]

    for selector in selectors:
        try:
            element = await page.query_selector(selector)
            if element and await element.is_visible():
                log.info(
                    "human_loop.submit_button_found",
                    selector=selector,
                    url=page.url,
                )
                await element.scroll_into_view_if_needed()
                await asyncio.sleep(0.3)
                await element.click()
                return True
        except Exception:
            continue

    return False


def _cancel_timeout_task(application_id: int) -> None:
    """Cancel the pending timeout task for an application."""
    task = _timeout_tasks.pop(application_id, None)
    if task and not task.done():
        task.cancel()
        log.debug(
            "human_loop.timeout_task.cancelled",
            application_id=application_id,
        )


# ---------------------------------------------------------------------------
# JavaScript helpers
# ---------------------------------------------------------------------------

_JS_SERIALIZE_FIELDS = """
() => {
    const result = {};

    function getSelector(el) {
        if (el.id) return `#${CSS.escape(el.id)}`;
        if (el.name) {
            const tag = el.tagName.toLowerCase();
            const matches = document.querySelectorAll(`${tag}[name="${el.name}"]`);
            if (matches.length === 1) return `${tag}[name="${CSS.escape(el.name)}"]`;
            const idx = Array.from(matches).indexOf(el);
            return `${tag}[name="${CSS.escape(el.name)}"]:nth-of-type(${idx + 1})`;
        }
        const tag = el.tagName.toLowerCase();
        const siblings = Array.from(el.parentElement
            ? el.parentElement.querySelectorAll(tag)
            : document.querySelectorAll(tag));
        const idx = siblings.indexOf(el);
        return idx >= 0 ? `${tag}:nth-of-type(${idx + 1})` : tag;
    }

    document.querySelectorAll('input, textarea, select').forEach(el => {
        const type = (el.type || '').toLowerCase();
        if (type === 'hidden' || type === 'submit' || type === 'button' || type === 'image') return;
        const ref = getSelector(el);
        if (!ref) return;

        if (type === 'checkbox' || type === 'radio') {
            result[ref] = el.checked;
        } else if (type === 'file') {
            // Cannot serialize file inputs — store path from data attribute if set
            result[ref] = el.getAttribute('data-filled-path') || '';
        } else {
            result[ref] = el.value || '';
        }
    });

    return result;
}
"""
