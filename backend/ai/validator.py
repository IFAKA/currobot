"""Field-level diff, fabrication detection, and language validation for adapted CVs."""
from __future__ import annotations

import re
from typing import Any

import structlog

from backend.ai import ollama_client
from backend.ai.prompts import FABRICATION_DETECTOR_V1

log = structlog.get_logger(__name__)


async def validate_cv(
    original: dict,
    adapted: dict,
    job_description: str,
    model: str,
) -> dict:
    """
    Validate an adapted CV against the original canonical CV.

    Returns:
        {
            "passed": bool,
            "errors": list[str],   # hard stops — block generation
            "warnings": list[str], # soft issues — log but continue
        }
    """
    errors: list[str] = []
    warnings: list[str] = []

    # ------------------------------------------------------------------
    # 1. PII integrity — name, phone, email must be identical (hard stop)
    # ------------------------------------------------------------------
    _check_pii_integrity(original, adapted, errors)

    # ------------------------------------------------------------------
    # 2. Experience integrity — same companies, roughly same dates (hard stop)
    # ------------------------------------------------------------------
    _check_experience_integrity(original, adapted, errors)

    # ------------------------------------------------------------------
    # 3. Fabrication detection via LLM (hard stop if fabricated skills found)
    # ------------------------------------------------------------------
    await _check_fabrication(original, adapted, model, errors)

    # ------------------------------------------------------------------
    # 4. Language consistency check (warning or hard stop)
    # ------------------------------------------------------------------
    _check_language_consistency(adapted, job_description, errors, warnings)

    passed = len(errors) == 0
    log.info(
        "validator.result",
        passed=passed,
        error_count=len(errors),
        warning_count=len(warnings),
        errors=errors,
        warnings=warnings,
    )
    return {"passed": passed, "errors": errors, "warnings": warnings}


# ---------------------------------------------------------------------------
# PII integrity
# ---------------------------------------------------------------------------

def _check_pii_integrity(original: dict, adapted: dict, errors: list[str]) -> None:
    """Name, email, and phone must be byte-for-byte identical."""
    for field in ("name", "email", "phone"):
        orig_val = (original.get(field) or "").strip()
        adap_val = (adapted.get(field) or "").strip()
        if orig_val and adap_val and orig_val != adap_val:
            errors.append(
                f"PII mismatch: field '{field}' changed from "
                f"'{orig_val}' to '{adap_val}'"
            )
            log.error(
                "validator.pii_mismatch",
                field=field,
                original=orig_val,
                adapted=adap_val,
            )
        elif orig_val and not adap_val:
            errors.append(f"PII removed: field '{field}' was present in original but missing in adapted CV")
            log.error("validator.pii_removed", field=field, original=orig_val)


# ---------------------------------------------------------------------------
# Experience integrity
# ---------------------------------------------------------------------------

def _check_experience_integrity(
    original: dict, adapted: dict, errors: list[str]
) -> None:
    """
    Every company in the original must appear in the adapted CV.
    Dates must be roughly equivalent (same year, ±1).
    """
    orig_exp: list[dict] = original.get("experience", [])
    adap_exp: list[dict] = adapted.get("experience", [])

    orig_companies = {
        _normalise_company(e.get("company", ""))
        for e in orig_exp
        if e.get("company")
    }
    adap_companies = {
        _normalise_company(e.get("company", ""))
        for e in adap_exp
        if e.get("company")
    }

    removed = orig_companies - adap_companies
    if removed:
        errors.append(
            f"Experience integrity: companies removed from adapted CV: {removed}"
        )
        log.error("validator.companies_removed", removed=list(removed))

    # Check that adapted CV doesn't have MORE entries than original
    # (fabricated new jobs)
    if len(adap_exp) > len(orig_exp):
        errors.append(
            f"Experience integrity: adapted CV has {len(adap_exp)} entries "
            f"but original has only {len(orig_exp)} — possible fabricated jobs"
        )
        log.error(
            "validator.extra_experience_entries",
            original_count=len(orig_exp),
            adapted_count=len(adap_exp),
        )

    # Date drift check — compare years for matching companies
    orig_by_company = {
        _normalise_company(e.get("company", "")): e for e in orig_exp
    }
    for adap_entry in adap_exp:
        company_key = _normalise_company(adap_entry.get("company", ""))
        orig_entry = orig_by_company.get(company_key)
        if not orig_entry:
            continue
        orig_years = _extract_years(orig_entry)
        adap_years = _extract_years(adap_entry)
        if orig_years and adap_years:
            orig_min, orig_max = min(orig_years), max(orig_years)
            adap_min, adap_max = min(adap_years), max(adap_years)
            if abs(orig_min - adap_min) > 1 or abs(orig_max - adap_max) > 1:
                errors.append(
                    f"Date drift at '{company_key}': original years {orig_years} "
                    f"vs adapted years {adap_years}"
                )
                log.error(
                    "validator.date_drift",
                    company=company_key,
                    original_years=orig_years,
                    adapted_years=adap_years,
                )


def _normalise_company(name: str) -> str:
    return re.sub(r"[^\w]", "", name.lower())


def _extract_years(entry: dict) -> list[int]:
    text = f"{entry.get('start_date', '')} {entry.get('end_date', '')}"
    return [int(y) for y in re.findall(r"\b(19|20)\d{2}\b", text)]


# ---------------------------------------------------------------------------
# Fabrication detection
# ---------------------------------------------------------------------------

async def _check_fabrication(
    original: dict,
    adapted: dict,
    model: str,
    errors: list[str],
) -> None:
    prompt = FABRICATION_DETECTOR_V1.format(
        original_cv=_cv_to_text(original),
        adapted_cv=_cv_to_text(adapted),
    )
    try:
        result = await ollama_client.generate_json(prompt, model, temperature=0.1)
        has_fabrication: bool = result.get("has_fabrication", False)
        fabricated: list[str] = result.get("fabricated_skills", [])

        log.info(
            "validator.fabrication_check",
            has_fabrication=has_fabrication,
            fabricated_items=fabricated,
        )

        if has_fabrication and fabricated:
            errors.append(
                f"Fabrication detected: adapted CV contains skills/items not in original: "
                f"{', '.join(fabricated)}"
            )
            log.error(
                "validator.fabrication_hard_stop",
                fabricated_skills=fabricated,
            )
        elif has_fabrication:
            # Model flagged fabrication but didn't list specifics
            errors.append(
                "Fabrication detected: AI flagged the adapted CV as containing "
                "fabricated content but could not list specific items"
            )
            log.error("validator.fabrication_unspecified")

    except Exception as e:
        log.warning(
            "validator.fabrication_check_failed",
            error=str(e),
            model=model,
        )
        # Do not block on fabrication check failure — add warning instead
        # (errors list is not modified here)


# ---------------------------------------------------------------------------
# Language consistency
# ---------------------------------------------------------------------------

def _check_language_consistency(
    adapted: dict,
    job_description: str,
    errors: list[str],
    warnings: list[str],
) -> None:
    try:
        from langdetect import detect, detect_langs  # type: ignore
        from langdetect.lang_detect_exception import LangDetectException  # type: ignore
    except ImportError:
        log.warning("validator.langdetect_not_installed")
        return

    adapted_text = _cv_to_text(adapted)
    if len(adapted_text) < 50:
        log.warning("validator.language_check_skipped", reason="text_too_short")
        return

    try:
        adapted_lang = detect(adapted_text)
        adapted_langs = detect_langs(adapted_text)
        adapted_confidence = next(
            (l.prob for l in adapted_langs if l.lang == adapted_lang), 0.0
        )
        log.info(
            "validator.adapted_language",
            lang=adapted_lang,
            confidence=round(adapted_confidence, 3),
        )
    except LangDetectException as e:
        log.warning("validator.language_detect_failed", stage="adapted", error=str(e))
        return

    if job_description and len(job_description) >= 50:
        try:
            jd_lang = detect(job_description)
            jd_langs = detect_langs(job_description)
            jd_confidence = next(
                (l.prob for l in jd_langs if l.lang == jd_lang), 0.0
            )
            log.info(
                "validator.job_description_language",
                lang=jd_lang,
                confidence=round(jd_confidence, 3),
            )

            if adapted_lang != jd_lang:
                msg = (
                    f"Language mismatch: adapted CV is '{adapted_lang}' "
                    f"(confidence={adapted_confidence:.2f}) but job description "
                    f"is '{jd_lang}' (confidence={jd_confidence:.2f})"
                )
                # Hard stop only when both detections are high confidence
                if adapted_confidence > 0.9 and jd_confidence > 0.9:
                    errors.append(msg)
                    log.error("validator.language_mismatch_hard_stop", msg=msg)
                else:
                    warnings.append(msg)
                    log.warning("validator.language_mismatch_warning", msg=msg)

        except LangDetectException as e:
            log.warning(
                "validator.language_detect_failed", stage="job_description", error=str(e)
            )

    # Additional check: flag if adapted CV appears to be non-Spanish with high confidence
    # (JobBot is a Spanish job market tool — CVs should default to Spanish)
    if adapted_lang not in ("es", "ca", "gl", "eu") and adapted_confidence > 0.9:
        warnings.append(
            f"Adapted CV appears to be in '{adapted_lang}' with high confidence "
            f"({adapted_confidence:.2f}). Spanish is expected for the Spanish job market."
        )
        log.warning(
            "validator.non_spanish_cv",
            lang=adapted_lang,
            confidence=round(adapted_confidence, 3),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cv_to_text(cv: dict) -> str:
    """Flatten a canonical/adapted CV dict to a single text block for language detection."""
    parts: list[str] = []

    if cv.get("name"):
        parts.append(cv["name"])
    if cv.get("summary"):
        parts.append(cv["summary"])

    for exp in cv.get("experience", []):
        if exp.get("title"):
            parts.append(exp["title"])
        if exp.get("company"):
            parts.append(exp["company"])
        parts.extend(exp.get("bullets", []))

    for edu in cv.get("education", []):
        if edu.get("degree"):
            parts.append(edu["degree"])
        if edu.get("institution"):
            parts.append(edu["institution"])

    skills = cv.get("skills", [])
    if skills:
        parts.append(", ".join(skills))

    if cv.get("skills_section_text"):
        parts.append(cv["skills_section_text"])

    return "\n".join(p for p in parts if p)
