"""Spanish cover letter generator — formal business letter format, max 300 words."""
from __future__ import annotations

from typing import Any

import structlog

from backend.ai import ollama_client
from backend.ai.prompts import COVER_LETTER_SPANISH_V1
from backend.config import settings

log = structlog.get_logger(__name__)

_MAX_WORDS = 300


async def generate_cover_letter(
    job: Any,
    cv_canonical: dict,
    profile: str,
) -> str:
    """
    Generate a formal Spanish cover letter tailored to the job and company.

    Args:
        job:           Job ORM instance (must have .title, .company, .description).
        cv_canonical:  Canonical CV dict with name, skills, experience, etc.
        profile:       CV profile key (cashier, stocker, logistics, frontend_dev, etc.)

    Returns:
        The cover letter as a plain string (ready to save to cover_letter_text).
    """
    company: str = getattr(job, "company", None) or "la empresa"
    job_title: str = getattr(job, "title", None) or profile
    job_description: str = getattr(job, "description", None) or ""

    candidate_name: str = cv_canonical.get("name", "")
    skills: str = ", ".join(cv_canonical.get("skills", [])[:10])

    # Build a brief experience summary from the most recent role
    experience_summary = _build_experience_summary(cv_canonical)

    prompt = COVER_LETTER_SPANISH_V1.format(
        company=company,
        job_title=job_title,
        job_description=job_description[:1000] if job_description else "(sin descripción)",
        candidate_name=candidate_name,
        skills=skills,
        experience_summary=experience_summary,
        cv_profile=profile,
    )

    try:
        result = await ollama_client.generate_json(
            prompt,
            model=await _get_model(),
            temperature=0.4,
        )
        letter: str = result.get("letter", "").strip()

        if not letter:
            log.warning(
                "cover_letter.empty_response",
                company=company,
                job_title=job_title,
            )
            return _fallback_letter(candidate_name, company, job_title, profile)

        # Enforce word limit (soft trim — do not cut mid-sentence)
        letter = _enforce_word_limit(letter, _MAX_WORDS)

        log.info(
            "cover_letter.generated",
            company=company,
            job_title=job_title,
            word_count=len(letter.split()),
            profile=profile,
        )
        return letter

    except Exception as e:
        log.error(
            "cover_letter.generation_failed",
            error=str(e),
            company=company,
            job_title=job_title,
        )
        return _fallback_letter(candidate_name, company, job_title, profile)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_model() -> str:
    from backend.ai import model_manager
    return await model_manager.get_active_model()


def _build_experience_summary(cv: dict) -> str:
    """Return a short summary of the most recent experience entry."""
    experience = cv.get("experience", [])
    if not experience:
        return ""
    most_recent = experience[0]
    title = most_recent.get("title", "")
    company = most_recent.get("company", "")
    bullets = most_recent.get("bullets", [])
    first_bullet = bullets[0] if bullets else ""
    parts = [p for p in (title, f"en {company}" if company else "", first_bullet) if p]
    return ". ".join(parts)[:300]


def _enforce_word_limit(text: str, max_words: int) -> str:
    """
    Trim text to at most max_words words, cutting at the last sentence boundary.
    """
    words = text.split()
    if len(words) <= max_words:
        return text

    # Find the last sentence boundary within the word limit
    truncated = " ".join(words[:max_words])
    last_period = max(
        truncated.rfind("."),
        truncated.rfind("!"),
        truncated.rfind("?"),
    )
    if last_period > 0:
        return truncated[: last_period + 1].strip()
    return truncated.strip()


def _fallback_letter(
    name: str,
    company: str,
    job_title: str,
    profile: str,
) -> str:
    """
    Minimal fallback letter when AI generation fails.
    Structured to be grammatically correct and not embarrassing.
    """
    salutation = f"Estimado/a equipo de {company},"
    body = (
        f"Me dirijo a ustedes para expresar mi interés en el puesto de {job_title} "
        f"en {company}. Con mi experiencia y habilidades, creo que puedo contribuir "
        f"positivamente a su equipo.\n\n"
        f"Adjunto mi currículum para su consideración y quedo a su disposición "
        f"para ampliar cualquier información que necesiten."
    )
    closing = "Atentamente,"
    signature = name or "El/La candidato/a"

    return f"{salutation}\n\n{body}\n\n{closing}\n{signature}"
