"""4-step CV adaptation: structural → AI rewrite → validate → quality check."""
from __future__ import annotations

import asyncio
import copy
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models import Application, ApplicationStatus
from backend.ai import model_manager, ollama_client, validator, quality_check
from backend.ai.prompts import CV_REWRITE_EXPERIENCE_V1, CV_GENERATE_SUMMARY_V1
from backend.config import settings

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Profile reframe configuration
# ---------------------------------------------------------------------------

PROFILE_REFRAME: dict[str, dict] = {
    "cashier": {
        "skills_emphasis": [
            "customer service",
            "POS systems",
            "cash handling",
            "team coordination",
        ],
        "title_map": {
            "Flowence": "retail customer service platform",
            "software": "business application",
        },
        "role_context": "cajero/dependiente en comercio minorista",
    },
    "stocker": {
        "skills_emphasis": [
            "inventory management",
            "stock control",
            "warehouse operations",
            "team coordination",
        ],
        "title_map": {
            "Flowence": "sistema de gestión de inventario",
            "software": "herramienta de seguimiento",
        },
        "role_context": "reponedor/mozo de almacén",
    },
    "logistics": {
        "skills_emphasis": [
            "logistics coordination",
            "inventory tracking",
            "organizational skills",
            "process optimization",
        ],
        "title_map": {
            "Flowence": "plataforma de gestión operativa",
        },
        "role_context": "mozo de almacén/operario logístico",
    },
    "frontend_dev": {
        "skills_emphasis": [
            "React",
            "Next.js",
            "TypeScript",
            "UI/UX",
            "responsive design",
            "REST APIs",
        ],
        "title_map": {},
        "role_context": "desarrollador frontend React/Next.js",
    },
    "fullstack_dev": {
        "skills_emphasis": [
            "React",
            "Node.js",
            "PostgreSQL",
            "TypeScript",
            "REST APIs",
            "Stripe",
            "JWT",
        ],
        "title_map": {},
        "role_context": "desarrollador fullstack React/Node.js",
    },
}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def adapt_cv(db: AsyncSession, application_id: int) -> dict:
    """
    Run the full 4-step CV adaptation pipeline for the given application.

    Steps:
        1. Structural transform (rule-based, no AI)
        2. AI experience rewrite (temperature=0.3)
        3. Validation gate (hard stop on failure)
        4. AI summary generation (temperature=0.5)
        5. Quality check (score, not a hard stop)
        6. Save adapted CV + PDF generation

    Returns:
        {"passed": bool, "quality_score": float, "pdf_path": str}
        or {"passed": False, "errors": list[str]} on validation failure
    """
    from backend.database.crud import get_application, transition_application, get_job

    app = await get_application(db, application_id)
    if not app:
        raise ValueError(f"Application {application_id} not found")

    canonical = app.cv_canonical_json
    if not canonical:
        raise ValueError("No canonical CV JSON for this application")

    profile: str = app.cv_profile
    model = await model_manager.get_active_model()

    # ------------------------------------------------------------------
    # Step 1: Structural transform (rule-based)
    # ------------------------------------------------------------------
    adapted = _structural_transform(canonical, profile)
    log.info(
        "cv_adapter.structural_done",
        application_id=application_id,
        profile=profile,
    )

    # ------------------------------------------------------------------
    # Step 2: AI experience rewrite (temp=0.3)
    # ------------------------------------------------------------------
    adapted = await _ai_rewrite_experience(adapted, app, profile, model)
    log.info("cv_adapter.ai_rewrite_done", application_id=application_id)

    # ------------------------------------------------------------------
    # Step 3: Validation gate (HARD STOP)
    # ------------------------------------------------------------------
    job = await get_job(db, app.job_id)
    job_description: str = ""
    if job:
        job_description = job.description or job.title or ""

    validation = await validator.validate_cv(canonical, adapted, job_description, model)
    if not validation["passed"]:
        log.error(
            "cv_adapter.validation_failed",
            application_id=application_id,
            errors=validation["errors"],
        )
        await transition_application(
            db,
            app,
            ApplicationStatus.cv_failed_validation,
            triggered_by="cv_adapter",
            note=str(validation["errors"]),
        )
        return {"passed": False, "errors": validation["errors"]}

    log.info("cv_adapter.validation_passed", application_id=application_id)

    # ------------------------------------------------------------------
    # Step 4: AI generate summary (temp=0.5)
    # ------------------------------------------------------------------
    adapted = await _ai_generate_summary(adapted, app, profile, model, job)

    # ------------------------------------------------------------------
    # Step 5: Quality check (score, not a hard block)
    # ------------------------------------------------------------------
    qc = await quality_check.score_cv(adapted, job_description, model)
    log.info(
        "cv_adapter.quality_check",
        application_id=application_id,
        score=qc["overall"],
        passed=qc["passed"],
    )

    if not qc["passed"]:
        log.warning(
            "cv_adapter.quality_below_threshold",
            application_id=application_id,
            score=qc["overall"],
            threshold=settings.quality_score_minimum,
        )

    # ------------------------------------------------------------------
    # Step 6: Persist adapted CV and transition status
    # ------------------------------------------------------------------
    await transition_application(
        db,
        app,
        ApplicationStatus.cv_ready,
        triggered_by="cv_adapter",
        cv_adapted_json=adapted,
        quality_score=qc["overall"],
        quality_rubric=qc,
    )

    # ------------------------------------------------------------------
    # Step 7: Generate PDF
    # ------------------------------------------------------------------
    from backend.documents.cv_generator import generate_cv_pdf

    pdf_path = await generate_cv_pdf(application_id, adapted, profile)
    app.cv_pdf_path = str(pdf_path)
    await db.flush()

    log.info(
        "cv_adapter.complete",
        application_id=application_id,
        quality_score=qc["overall"],
        pdf_path=str(pdf_path),
    )

    return {
        "passed": True,
        "quality_score": qc["overall"],
        "pdf_path": str(pdf_path),
    }


# ---------------------------------------------------------------------------
# Step 1: Structural transform
# ---------------------------------------------------------------------------

def _structural_transform(canonical: dict, profile: str) -> dict:
    """
    Rule-based reframing — no AI, no omissions, only recontextualization.

    - Apply title_map substitutions to every bullet in every experience entry.
    - Reorder skills to put profile-relevant ones first.
    """
    adapted = copy.deepcopy(canonical)
    reframe = PROFILE_REFRAME.get(profile, {})
    title_map: dict[str, str] = reframe.get("title_map", {})

    # Reframe experience bullets
    for exp in adapted.get("experience", []):
        new_bullets: list[str] = []
        for bullet in exp.get("bullets", []):
            for original, replacement in title_map.items():
                bullet = bullet.replace(original, replacement)
            new_bullets.append(bullet)
        exp["bullets"] = new_bullets

    # Reorder skills: profile-relevant first, then the rest
    emphasis: list[str] = reframe.get("skills_emphasis", [])
    skills: list[str] = adapted.get("skills", [])
    emphasized = [s for s in skills if any(e.lower() in s.lower() for e in emphasis)]
    others = [s for s in skills if s not in emphasized]
    adapted["skills"] = emphasized + others

    return adapted


# ---------------------------------------------------------------------------
# Step 2: AI experience rewrite
# ---------------------------------------------------------------------------

async def _ai_rewrite_experience(
    adapted: dict,
    app: Application,
    profile: str,
    model: str,
) -> dict:
    reframe = PROFILE_REFRAME.get(profile, {})
    role_context = reframe.get("role_context", profile)

    prompt = CV_REWRITE_EXPERIENCE_V1.format(
        role_context=role_context,
        experience=str(adapted.get("experience", [])),
        skills=", ".join(adapted.get("skills", [])[:15]),
    )

    try:
        result = await ollama_client.generate_json(
            prompt, model, temperature=settings.cv_rewrite_temperature
        )
        if "experience" in result and isinstance(result["experience"], list):
            adapted["experience"] = result["experience"]
            log.info(
                "cv_adapter.experience_rewritten",
                entry_count=len(result["experience"]),
            )
        if "skills_section" in result:
            adapted["skills_section_text"] = result["skills_section"]
    except Exception as e:
        log.warning(
            "cv_adapter.ai_rewrite_failed",
            error=str(e),
            profile=profile,
        )
        # Non-fatal: fall through with structurally transformed content

    return adapted


# ---------------------------------------------------------------------------
# Step 4: AI summary generation
# ---------------------------------------------------------------------------

async def _ai_generate_summary(
    adapted: dict,
    app: Application,
    profile: str,
    model: str,
    job: Any,
) -> dict:
    company: str = getattr(job, "company", None) or "la empresa"
    job_title: str = getattr(job, "title", None) or profile

    first_exp_title = ""
    experience = adapted.get("experience", [])
    if experience and isinstance(experience[0], dict):
        first_exp_title = experience[0].get("title", "")

    prompt = CV_GENERATE_SUMMARY_V1.format(
        company=company,
        job_title=job_title,
        candidate_name=adapted.get("name", ""),
        skills=", ".join(adapted.get("skills", [])[:10]),
        experience_summary=first_exp_title,
    )

    try:
        result = await ollama_client.generate_json(
            prompt, model, temperature=settings.cv_summary_temperature
        )
        new_summary = result.get("summary", "")
        if new_summary:
            adapted["summary"] = new_summary
            log.info("cv_adapter.summary_generated", length=len(new_summary))
        else:
            log.warning("cv_adapter.summary_empty_response")
    except Exception as e:
        log.warning(
            "cv_adapter.summary_failed",
            error=str(e),
            profile=profile,
        )
        # Non-fatal: keep existing summary or empty

    return adapted
