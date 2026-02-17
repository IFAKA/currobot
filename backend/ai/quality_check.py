"""Quality check: score an adapted CV against a job description using a structured rubric."""
from __future__ import annotations

import json
from typing import Any

import structlog

from backend.ai import ollama_client
from backend.ai.prompts import QUALITY_CHECK_RUBRIC_V1
from backend.config import settings

log = structlog.get_logger(__name__)

_SCORE_FIELDS = ("ats_keyword_match", "language_consistency", "relevance")


async def score_cv(
    adapted_cv: dict,
    job_description: str,
    model: str,
) -> dict:
    """
    Score an adapted CV against a job description using a structured rubric.

    Returns:
        {
            "ats_keyword_match": float,    # 0-10
            "language_consistency": float, # 0-10
            "relevance": float,            # 0-10
            "overall": float,              # weighted average
            "passed": bool,                # overall >= settings.quality_score_minimum
            "notes": str,                  # AI feedback
        }
    """
    prompt = QUALITY_CHECK_RUBRIC_V1.format(
        job_description=job_description or "(no job description provided)",
        adapted_cv=json.dumps(adapted_cv, ensure_ascii=False, indent=2)[:3000],
    )

    try:
        result = await ollama_client.generate_json(prompt, model, temperature=0.1)
        rubric = _parse_rubric(result)
    except Exception as e:
        log.error("quality_check.ai_failed", error=str(e), model=model)
        # Fallback rubric — below threshold to be safe
        rubric = _fallback_rubric(str(e))

    rubric["passed"] = rubric["overall"] >= settings.quality_score_minimum

    log.info(
        "quality_check.scored",
        ats_keyword_match=rubric["ats_keyword_match"],
        language_consistency=rubric["language_consistency"],
        relevance=rubric["relevance"],
        overall=rubric["overall"],
        passed=rubric["passed"],
        notes=rubric.get("notes", ""),
        model=model,
        minimum_threshold=settings.quality_score_minimum,
    )

    if not rubric["passed"]:
        log.warning(
            "quality_check.below_threshold",
            overall=rubric["overall"],
            threshold=settings.quality_score_minimum,
        )

    return rubric


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_rubric(raw: dict) -> dict:
    """Validate and coerce rubric fields from AI response."""
    rubric: dict[str, Any] = {}

    for field in _SCORE_FIELDS:
        value = raw.get(field, 5.0)
        try:
            score = float(value)
            rubric[field] = max(0.0, min(10.0, score))
        except (TypeError, ValueError):
            log.warning("quality_check.invalid_score", field=field, value=value)
            rubric[field] = 5.0

    # Compute or accept overall — use weighted mean if not provided
    if "overall" in raw:
        try:
            rubric["overall"] = max(0.0, min(10.0, float(raw["overall"])))
        except (TypeError, ValueError):
            rubric["overall"] = _weighted_average(rubric)
    else:
        rubric["overall"] = _weighted_average(rubric)

    rubric["notes"] = str(raw.get("notes", "")).strip()[:500]

    # Accept AI-provided passed flag but override with our threshold logic
    # (the override happens in the calling function after this returns)
    rubric["passed"] = bool(raw.get("passed", False))

    return rubric


def _weighted_average(rubric: dict) -> float:
    """
    Compute weighted average of sub-scores.

    Weights:
    - ats_keyword_match: 40%  (most important for getting past ATS)
    - relevance: 40%          (critical for human review)
    - language_consistency: 20%
    """
    weights = {
        "ats_keyword_match": 0.40,
        "relevance": 0.40,
        "language_consistency": 0.20,
    }
    total = sum(rubric.get(k, 5.0) * w for k, w in weights.items())
    return round(total, 2)


def _fallback_rubric(error_note: str) -> dict:
    """Return a below-threshold rubric when AI scoring fails."""
    return {
        "ats_keyword_match": 0.0,
        "language_consistency": 0.0,
        "relevance": 0.0,
        "overall": 0.0,
        "passed": False,
        "notes": f"Quality check failed due to AI error: {error_note[:200]}",
    }
