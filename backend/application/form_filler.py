"""Fill form fields with human-behavior simulation using Playwright."""
from __future__ import annotations

import asyncio
import random
from pathlib import Path
from typing import Any, Optional

import structlog

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Semantic field mapping
# ---------------------------------------------------------------------------

FIELD_MAP: dict[str, str] = {
    # Name variants
    "nombre": "name",
    "name": "name",
    "apellido": "name",
    "apellidos": "name",
    "full name": "name",
    "nombre completo": "name",
    "nombre y apellidos": "name",
    # Email
    "email": "email",
    "correo": "email",
    "correo electrónico": "email",
    "e-mail": "email",
    "mail": "email",
    # Phone
    "telefono": "phone",
    "teléfono": "phone",
    "phone": "phone",
    "móvil": "phone",
    "movil": "phone",
    "mobile": "phone",
    "celular": "phone",
    "tel": "phone",
    # Cover letter
    "carta": "cover_letter",
    "carta de presentación": "cover_letter",
    "motivacion": "cover_letter",
    "motivación": "cover_letter",
    "presentacion": "cover_letter",
    "presentación": "cover_letter",
    "cover letter": "cover_letter",
    "cover_letter": "cover_letter",
    "por qué": "cover_letter",
    "why": "cover_letter",
    # CV file
    "cv": "cv_file",
    "curriculum": "cv_file",
    "currículum": "cv_file",
    "resume": "cv_file",
    "adjuntar cv": "cv_file",
    "upload cv": "cv_file",
    "upload resume": "cv_file",
    # LinkedIn
    "linkedin": "linkedin",
    "linkedin url": "linkedin",
    "perfil linkedin": "linkedin",
    # GitHub
    "github": "github",
    "github url": "github",
    "perfil github": "github",
    # Location
    "ubicacion": "location",
    "ubicación": "location",
    "ciudad": "location",
    "city": "location",
    "location": "location",
    "lugar de residencia": "location",
    # Salary
    "salario": "salary_expectation",
    "salario esperado": "salary_expectation",
    "pretensión salarial": "salary_expectation",
    "salary": "salary_expectation",
    "salary expectation": "salary_expectation",
    # Availability
    "disponibilidad": "availability",
    "disponibilidad para incorporación": "availability",
    "availability": "availability",
    "start date": "availability",
    "fecha de incorporación": "availability",
}

# Default values for fields that are not in the CV
_DEFAULT_VALUES: dict[str, str] = {
    "salary_expectation": "según convenio",
    "availability": "inmediata",
}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def fill_form(
    page: Any,
    fields: list[dict],
    cv_data: dict,
    job_data: dict,
) -> dict:
    """
    Fill form fields with human-behavior simulation.

    Args:
        page:      Playwright page object.
        fields:    Output of form_detector.detect_fields().
        cv_data:   Canonical or adapted CV dict.
        job_data:  Job dict (must have pdf_path for file upload).

    Returns:
        Serialized dict of {field_ref: value_filled} for DB storage.
    """
    filled: dict[str, Any] = {}
    cv_pdf_path: str = str(job_data.get("cv_pdf_path", ""))

    for field in fields:
        if not field.get("visible", True):
            log.debug("form_filler.skipping_hidden", ref=field.get("ref"))
            continue
        if field.get("type") == "hidden":
            continue

        semantic_key = _resolve_semantic_key(field)
        value = _get_value(semantic_key, cv_data, job_data, field)

        if value is None:
            log.debug(
                "form_filler.no_value",
                label=field.get("label"),
                semantic_key=semantic_key,
            )
            continue

        try:
            filled_value = await _fill_field(page, field, value, cv_pdf_path)
            if filled_value is not None:
                filled[field.get("ref", field.get("name", ""))] = filled_value
                log.info(
                    "form_filler.filled",
                    label=field.get("label", ""),
                    type=field.get("type"),
                    semantic=semantic_key,
                )
        except Exception as e:
            log.warning(
                "form_filler.fill_failed",
                label=field.get("label", ""),
                ref=field.get("ref", ""),
                error=str(e),
            )

        # Human-like delay between fields
        await asyncio.sleep(random.uniform(0.3, 1.5))

    log.info(
        "form_filler.complete",
        filled_count=len(filled),
        total_fields=len(fields),
        url=page.url,
    )
    return filled


# ---------------------------------------------------------------------------
# Field resolution helpers
# ---------------------------------------------------------------------------

def _resolve_semantic_key(field: dict) -> str:
    """Map a field dict to a semantic key using FIELD_MAP."""
    label = (field.get("label") or "").lower().strip()
    name = (field.get("name") or "").lower().strip()
    field_type = field.get("type", "")

    # Direct label match
    if label in FIELD_MAP:
        return FIELD_MAP[label]

    # Partial label match
    for pattern, key in FIELD_MAP.items():
        if pattern in label or pattern in name:
            return key

    # Type-based fallback
    if field_type == "email":
        return "email"
    if field_type == "tel":
        return "phone"
    if field_type == "file":
        return "cv_file"

    return label or name or "unknown"


def _get_value(
    semantic_key: str,
    cv_data: dict,
    job_data: dict,
    field: dict,
) -> Optional[Any]:
    """Resolve the value to fill for a given semantic key."""
    cv_values: dict[str, Any] = {
        "name": cv_data.get("name", ""),
        "email": cv_data.get("email", ""),
        "phone": cv_data.get("phone", ""),
        "location": cv_data.get("location", ""),
        "linkedin": cv_data.get("linkedin", ""),
        "github": cv_data.get("github", ""),
        "cover_letter": job_data.get("cover_letter_text", cv_data.get("summary", "")),
        "cv_file": job_data.get("cv_pdf_path", ""),
        **_DEFAULT_VALUES,
    }

    value = cv_values.get(semantic_key)
    if value:
        return value

    # For select fields, try to find a matching option
    if field.get("type") == "select" and field.get("options"):
        return None  # Let caller handle select with partial matching

    return None


# ---------------------------------------------------------------------------
# Field filling logic
# ---------------------------------------------------------------------------

async def _fill_field(
    page: Any,
    field: dict,
    value: Any,
    cv_pdf_path: str,
) -> Optional[Any]:
    """Fill a single field. Returns the value that was filled, or None on skip."""
    ref = field.get("ref", "")
    field_type = field.get("type", "text")

    # Scroll to and focus the element
    try:
        await page.evaluate(
            f"""(ref) => {{
                const el = document.querySelector(ref);
                if (el) {{
                    el.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
                    el.focus();
                }}
            }}""",
            ref,
        )
        await asyncio.sleep(random.uniform(0.1, 0.3))
    except Exception:
        pass

    if field_type == "file":
        if cv_pdf_path and Path(cv_pdf_path).exists():
            await page.set_input_files(ref, cv_pdf_path)
            return cv_pdf_path
        else:
            log.warning("form_filler.cv_file_missing", path=cv_pdf_path)
            return None

    elif field_type in ("text", "email", "tel", "number", "url"):
        text_value = str(value)
        await page.click(ref)
        await asyncio.sleep(random.uniform(0.05, 0.15))
        # Clear existing content
        await page.fill(ref, "")
        # Type with human-like speed for important fields
        is_important = field_type in ("email", "tel") or len(text_value) > 30
        if is_important:
            await page.type(ref, text_value, delay=random.randint(40, 100))
        else:
            await page.fill(ref, text_value)
        await asyncio.sleep(random.uniform(0.1, 0.3))
        return text_value

    elif field_type == "textarea":
        text_value = str(value)
        await page.click(ref)
        await asyncio.sleep(random.uniform(0.1, 0.2))
        await page.fill(ref, "")
        # Type cover letter character by character for realism
        await page.type(ref, text_value, delay=random.randint(20, 60))
        await asyncio.sleep(random.uniform(0.2, 0.5))
        return text_value

    elif field_type == "select":
        options: list[dict] = field.get("options", [])
        str_value = str(value).lower()
        # Try exact match first, then partial
        matched_value = None
        for opt in options:
            opt_text = opt.get("text", "").lower()
            opt_val = opt.get("value", "").lower()
            if str_value in (opt_text, opt_val):
                matched_value = opt.get("value")
                break
        if not matched_value:
            for opt in options:
                opt_text = opt.get("text", "").lower()
                opt_val = opt.get("value", "").lower()
                if str_value in opt_text or str_value in opt_val:
                    matched_value = opt.get("value")
                    break
        if matched_value:
            await page.click(ref)
            await asyncio.sleep(random.uniform(0.2, 0.5))
            await page.select_option(ref, matched_value)
            await asyncio.sleep(random.uniform(0.1, 0.3))
            return matched_value
        return None

    elif field_type == "radio":
        if str(value).lower() in ("true", "yes", "sí", "si", "1"):
            await asyncio.sleep(random.uniform(0.2, 0.4))
            await page.click(ref)
            await asyncio.sleep(random.uniform(0.1, 0.2))
            return True
        return None

    elif field_type == "checkbox":
        bool_value = str(value).lower() in ("true", "yes", "sí", "si", "1", "on")
        current = await page.is_checked(ref)
        if current != bool_value:
            await asyncio.sleep(random.uniform(0.2, 0.4))
            await page.click(ref)
            await asyncio.sleep(random.uniform(0.1, 0.2))
        return bool_value

    elif field_type == "date":
        text_value = str(value)
        await page.fill(ref, text_value)
        return text_value

    elif field_type == "range":
        # Set value via JavaScript for range inputs
        num_value = str(value)
        await page.evaluate(
            f"""(ref) => {{
                const el = document.querySelector(ref);
                if (el) {{
                    el.value = '{num_value}';
                    el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                }}
            }}""",
            ref,
        )
        return num_value

    return None
