"""
Visa eligibility filter for the "canje" (student stay → work authorization).

Rules (Spain 2025/2026 — Reglamento de Extranjería):
  - Contract must be indefinido (permanent).
    → Skip if explicitly temporal: "temporal", "por obra", "eventual",
      "interinidad", "sustitución", "fijo discontinuo", etc.
  - Salary must be ≥ SMI (€15,876 gross/year = €1,134/month × 14 pays).
    → Skip only if an explicitly stated salary is entirely below the threshold.
    → If no salary is mentioned, let it through.
  - Must be jornada completa (full-time).
    → Skip if explicitly part-time: "media jornada", "tiempo parcial",
      "part-time", specific low-hour mentions, etc.

Principle: be conservative. Only skip a job when it *explicitly* declares
a disqualifying condition. Ambiguity → let it through.
"""
from __future__ import annotations

import re
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Thresholds (update each January when new SMI is published)
# ---------------------------------------------------------------------------

# SMI 2024-2025: €1,134/month × 14 pays = €15,876/year
# For monthly salary checks we use the 14-pays monthly basis (more lenient,
# avoids false positives since Spanish contracts often include 14 pagas).
# For annual salary checks we compare directly against the annual figure.
SMI_MONTHLY_GROSS = 1_134.0   # €/month (14-pays basis)
SMI_ANNUAL_GROSS  = 15_876.0  # €/year

# ---------------------------------------------------------------------------
# Keyword sets  (all lowercase, matched against lowercased text)
# ---------------------------------------------------------------------------

# Explicit temporal contract keywords
_TEMPORAL_KEYWORDS = {
    "temporal",
    "por obra",
    "obra y servicio",
    "obra o servicio",
    "eventual",
    "interinidad",
    "interino",
    "interina",
    "sustitución",
    "sustitucio",
    "sustitución",
    "fijo discontinuo",
    "fijo-discontinuo",
    "fixed-term",
    "fixed term",
    "temporary contract",
    "contrato de duración determinada",
}

# Explicit part-time keywords
_PARTTIME_KEYWORDS = {
    "media jornada",
    "medio jornada",
    "tiempo parcial",
    "part time",
    "part-time",
    "jornada parcial",
    "jornada reducida",
}

# Part-time hour patterns: e.g. "20 horas", "25h/semana", "30h semanales"
# We consider anything strictly under 35h/week to be part-time
_HOUR_PATTERN = re.compile(
    r"\b(\d{1,2})\s*(?:h(?:oras?)?|hrs?)(?:/semana|semanales|\s+semana|\s+semanales|/week)?\b",
    re.IGNORECASE,
)

# Salary parsing: capture a numeric amount and an optional period indicator
# Handles: "1.200€/mes", "14.000 €/año", "12000 euros anuales", "1200-1500€/mes"
_SALARY_PATTERN = re.compile(
    r"(\d[\d.,]*)\s*(?:€|eur(?:os?)?)\s*(?:[-/]\s*(\d[\d.,]*))?.*?"
    r"(mes(?:es)?|month|año|ano|anual|year|annual)?",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_eligible(job_data: dict) -> tuple[bool, Optional[str]]:
    """
    Return (True, None) if the job passes all visa-eligibility checks,
    or (False, reason_str) if it is explicitly disqualified.

    job_data keys used: title, description, contract_type, salary_raw.
    All are optional — missing fields are treated as "not mentioned → pass".
    """
    title        = (job_data.get("title") or "").lower()
    description  = (job_data.get("description") or "").lower()
    contract_raw = (job_data.get("contract_type") or "").lower()
    salary_raw   = (job_data.get("salary_raw") or "").lower()

    # Combine all text fields for keyword scanning
    full_text = f"{title} {contract_type_expanded(contract_raw)} {description}"

    # ------------------------------------------------------------------
    # 1. Temporal contract check
    # ------------------------------------------------------------------
    matched_temporal = _find_keyword(full_text, _TEMPORAL_KEYWORDS)
    if matched_temporal:
        return False, f"temporal contract detected: '{matched_temporal}'"

    # ------------------------------------------------------------------
    # 2. Part-time check (keywords)
    # ------------------------------------------------------------------
    matched_parttime = _find_keyword(full_text, _PARTTIME_KEYWORDS)
    if matched_parttime:
        return False, f"part-time detected: '{matched_parttime}'"

    # ------------------------------------------------------------------
    # 3. Part-time check (explicit low-hour mention)
    # ------------------------------------------------------------------
    hours_reason = _check_hours(full_text)
    if hours_reason:
        return False, hours_reason

    # ------------------------------------------------------------------
    # 4. Salary check
    # ------------------------------------------------------------------
    salary_reason = _check_salary(salary_raw, description)
    if salary_reason:
        return False, salary_reason

    return True, None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def contract_type_expanded(raw: str) -> str:
    """Map common short codes to full phrases for easier keyword matching."""
    mapping = {
        "td":  "temporal",
        "ti":  "indefinido",
        "fp":  "formación profesional",
        "p":   "practicas",
    }
    return mapping.get(raw.strip(), raw)


def _find_keyword(text: str, keywords: set[str]) -> Optional[str]:
    """Return the first matching keyword found in text, or None."""
    for kw in keywords:
        if kw in text:
            return kw
    return None


def _check_hours(text: str) -> Optional[str]:
    """
    Return a disqualification reason if text explicitly mentions working
    fewer than 35 hours/week, else None.
    """
    for m in _HOUR_PATTERN.finditer(text):
        hours = int(m.group(1))
        if hours < 35:
            return f"part-time hours detected: {hours}h/week"
    return None


def _check_salary(salary_raw: str, description: str) -> Optional[str]:
    """
    Parse any salary figure found in salary_raw (primary) or description
    (fallback). Return a disqualification reason if every parseable amount
    is below the SMI threshold, else None.

    Uses separate thresholds for annual vs monthly figures to avoid
    the 12-pay/14-pay ambiguity common in Spanish job postings.

    Conservative: if we cannot parse a clear amount, return None (let through).
    """
    text = salary_raw if salary_raw else description
    if not text:
        return None

    candidates: list[tuple[float, str]] = _parse_salary_amounts(text)
    if not candidates:
        return None

    # Keep only amounts that are above the relevant threshold.
    # If *any* candidate passes, the job is not disqualified.
    passing = []
    for amount, period_type in candidates:
        if period_type == "annual":
            if amount >= SMI_ANNUAL_GROSS:
                passing.append((amount, period_type))
        else:  # monthly
            if amount >= SMI_MONTHLY_GROSS:
                passing.append((amount, period_type))

    if passing:
        return None

    # All candidates are below threshold — disqualify using the most
    # informative one for the reason message.
    best_amount, best_period = max(candidates, key=lambda x: x[0])
    if best_period == "annual":
        return (
            f"salary too low for canje: €{best_amount:.0f}/year "
            f"(minimum: €{SMI_ANNUAL_GROSS:.0f}/year)"
        )
    return (
        f"salary too low for canje: ~€{best_amount:.0f}/month "
        f"(minimum: €{SMI_MONTHLY_GROSS:.0f}/month)"
    )


def _parse_salary_amounts(text: str) -> list[tuple[float, str]]:
    """
    Extract all numeric salary mentions and return (amount, period_type) tuples
    where period_type is "annual" or "monthly".

    Returns an empty list if nothing parseable is found.

    Handles:
      - "1.200 €/mes"           → (1200.0, "monthly")
      - "14.000 €/año"          → (14000.0, "annual")
      - "1200-1500 €/mes"       → (1200.0, "monthly"), (1500.0, "monthly")
      - "12000 euros anuales"   → (12000.0, "annual")
      - Bare numbers without currency/period label → ignored (false-positive risk)
    """
    pattern = re.compile(
        r"(\d[\d.,]*)(?:\s*[-–]\s*(\d[\d.,]*))?"          # amount or range
        r"\s*(?:€|eur(?:os?)?)?"                           # currency (optional)
        r"\s*/?\s*"
        r"(mes(?:es)?|month|año|ano|anual(?:es)?|year|annual)?",  # period
        re.IGNORECASE,
    )

    results: list[tuple[float, str]] = []
    for m in pattern.finditer(text):
        raw1   = m.group(1)
        raw2   = m.group(2)
        period = (m.group(3) or "").lower()

        surrounding = text[max(0, m.start()-5): m.end()+5]
        has_currency = bool(re.search(r"€|eur", surrounding, re.IGNORECASE))
        if not period and not has_currency:
            continue

        amounts = [_parse_number(raw1)]
        if raw2:
            amounts.append(_parse_number(raw2))
        amounts = [a for a in amounts if a and a > 0]
        if not amounts:
            continue

        for amount in amounts:
            if period in ("año", "ano", "anual", "anuales", "year", "annual"):
                period_type = "annual"
                # Sanity: annual salary between €5k and €500k
                if not (5_000 < amount < 500_000):
                    continue
            elif period in ("mes", "meses", "month"):
                period_type = "monthly"
                # Sanity: monthly salary between €300 and €30k
                if not (300 < amount < 30_000):
                    continue
            else:
                # No period label — heuristic: > 2000 is likely annual
                if amount > 2_000:
                    period_type = "annual"
                    if not (5_000 < amount < 500_000):
                        continue
                else:
                    period_type = "monthly"
                    if not (300 < amount < 30_000):
                        continue

            results.append((amount, period_type))

    return results


def _parse_number(raw: str) -> Optional[float]:
    """Convert '1.200,50' or '1,200.50' or '1200' to float."""
    if not raw:
        return None
    s = raw.replace(" ", "")
    # Detect European format (dot as thousands separator, comma as decimal)
    if re.search(r"\d\.\d{3}", s) and "," not in s:
        s = s.replace(".", "")          # "1.200" → "1200"
    elif "," in s and "." in s:
        # Could be "1,200.50" (US) or "1.200,50" (EU)
        if s.index(",") < s.index("."):
            s = s.replace(",", "")     # US: remove thousands comma
        else:
            s = s.replace(".", "").replace(",", ".")  # EU
    elif "," in s:
        s = s.replace(",", ".")        # "1200,50" → "1200.50"
    try:
        return float(s)
    except ValueError:
        return None
