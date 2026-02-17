"""Multi-signal confirmation detection after form submission."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import structlog

from backend.config import CV_GENERATED_DIR

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Signal patterns
# ---------------------------------------------------------------------------

_SUCCESS_PATTERNS: list[str] = [
    "gracias",
    "solicitud recibida",
    "application submitted",
    "thank you",
    "hemos recibido",
    "confirmación",
    "confirmacion",
    "éxito",
    "exito",
    "your application",
    "tu solicitud",
    "candidatura recibida",
    "candidatura enviada",
    "successfully submitted",
    "sent successfully",
    "we have received",
    "su candidatura",
    "enhorabuena",
    "felicidades",
    "proceso de selección",
    "nos pondremos en contacto",
    "we will be in touch",
    "we'll be in touch",
    "review your application",
    "application complete",
    "solicitud completada",
    "inscripción realizada",
    "inscripcion realizada",
]

_ERROR_PATTERNS: list[str] = [
    "error",
    "inténtalo de nuevo",
    "intentalo de nuevo",
    "try again",
    "failed",
    "falló",
    "fallo",
    "something went wrong",
    "algo salió mal",
    "algo salio mal",
    "vuelve a intentar",
    "hubo un problema",
    "no se pudo",
    "could not submit",
    "submission failed",
    "por favor revisa",
    "please review",
    "invalid",
    "inválido",
    "invalido",
    "required field",
    "campo requerido",
    "campo obligatorio",
]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def detect_confirmation(
    page: Any,
    application_id: int,
    timeout_seconds: int = 10,
) -> dict:
    """
    Detect submission confirmation using multiple signals.

    Checks (in order):
    1. URL change detection
    2. Success text patterns in page content
    3. Error text patterns (set confirmed=False and return early)
    4. Form disappearance from DOM

    Takes screenshots at start and end of detection window.

    Returns:
        {
            "confirmed": bool,
            "signal": str,            # "url_change" | "success_text" | "form_gone" |
                                      # "error_detected" | "submitted_ambiguous"
            "screenshot_path": str,   # path to final screenshot
        }
    """
    out_dir = CV_GENERATED_DIR / str(application_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Take initial screenshot
    initial_screenshot = str(out_dir / "confirmation_start.png")
    try:
        await page.screenshot(path=initial_screenshot, full_page=True)
        log.info(
            "confirm_detector.initial_screenshot",
            path=initial_screenshot,
            application_id=application_id,
        )
    except Exception as e:
        log.warning("confirm_detector.screenshot_failed", stage="initial", error=str(e))

    initial_url = page.url
    form_present_initially = await _form_exists(page)

    result = {
        "confirmed": False,
        "signal": "submitted_ambiguous",
        "screenshot_path": "",
    }

    # Run detection for up to timeout_seconds
    deadline = asyncio.get_event_loop().time() + timeout_seconds
    check_interval = 0.5

    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(check_interval)

        # ------------------------------------------------------------------
        # Signal 1: URL change
        # ------------------------------------------------------------------
        current_url = page.url
        if current_url != initial_url:
            log.info(
                "confirm_detector.url_changed",
                from_url=initial_url,
                to_url=current_url,
                application_id=application_id,
            )
            # Verify the new URL is a confirmation page, not an error/redirect
            page_text = await _get_page_text(page)
            if _has_error_pattern(page_text):
                result.update(
                    confirmed=False,
                    signal="error_detected",
                )
                break
            result.update(
                confirmed=True,
                signal="url_change",
            )
            break

        # ------------------------------------------------------------------
        # Signal 2: Success text in page content
        # ------------------------------------------------------------------
        try:
            page_text = await _get_page_text(page)

            if _has_error_pattern(page_text):
                log.warning(
                    "confirm_detector.error_text_found",
                    application_id=application_id,
                )
                result.update(
                    confirmed=False,
                    signal="error_detected",
                )
                break

            if _has_success_pattern(page_text):
                log.info(
                    "confirm_detector.success_text_found",
                    application_id=application_id,
                )
                result.update(
                    confirmed=True,
                    signal="success_text",
                )
                break

        except Exception as e:
            log.warning("confirm_detector.text_check_failed", error=str(e))

        # ------------------------------------------------------------------
        # Signal 4: Form disappeared from DOM
        # ------------------------------------------------------------------
        if form_present_initially:
            form_now = await _form_exists(page)
            if not form_now:
                log.info(
                    "confirm_detector.form_disappeared",
                    application_id=application_id,
                )
                result.update(
                    confirmed=True,
                    signal="form_gone",
                )
                break

    # ------------------------------------------------------------------
    # Take final screenshot
    # ------------------------------------------------------------------
    final_screenshot = str(out_dir / "confirmation.png")
    try:
        await page.screenshot(path=final_screenshot, full_page=True)
        result["screenshot_path"] = final_screenshot
        log.info(
            "confirm_detector.final_screenshot",
            path=final_screenshot,
            application_id=application_id,
        )
    except Exception as e:
        log.warning("confirm_detector.screenshot_failed", stage="final", error=str(e))
        result["screenshot_path"] = initial_screenshot

    log.info(
        "confirm_detector.result",
        confirmed=result["confirmed"],
        signal=result["signal"],
        application_id=application_id,
    )
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_page_text(page: Any) -> str:
    """Extract visible text content from the page."""
    try:
        text: str = await page.evaluate(
            "() => document.body ? document.body.innerText : ''"
        )
        return text.lower()
    except Exception:
        return ""


async def _form_exists(page: Any) -> bool:
    """Check whether at least one form element exists in the DOM."""
    try:
        count: int = await page.evaluate(
            "() => document.querySelectorAll('form').length"
        )
        return count > 0
    except Exception:
        return False


def _has_success_pattern(text: str) -> bool:
    return any(pattern in text for pattern in _SUCCESS_PATTERNS)


def _has_error_pattern(text: str) -> bool:
    # "error" is common in many non-error contexts, require it to appear
    # alongside other indicators or in a prominent position
    error_count = sum(1 for pattern in _ERROR_PATTERNS if pattern in text)
    # Single "error" hit is not enough unless it's a critical term
    critical_errors = {"failed", "submission failed", "could not submit", "fallo"}
    for ce in critical_errors:
        if ce in text:
            return True
    return error_count >= 2
