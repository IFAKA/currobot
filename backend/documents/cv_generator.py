"""Adapted CV JSON → ATS-safe PDF using ReportLab."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import structlog

from backend.config import CV_GENERATED_DIR

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Color constants (RGB tuples 0-1)
# ---------------------------------------------------------------------------
_BLACK = (0, 0, 0)
_DARK_GRAY = (0.25, 0.25, 0.25)
_MEDIUM_GRAY = (0.45, 0.45, 0.45)
_LIGHT_GRAY = (0.85, 0.85, 0.85)

# ---------------------------------------------------------------------------
# Layout constants (points; 1pt = 1/72 inch)
# ---------------------------------------------------------------------------
_PAGE_MARGIN = 54  # 0.75 inch margins
_FONT_NAME = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"
_FONT_SIZE_NAME = 20
_FONT_SIZE_SECTION = 12
_FONT_SIZE_BODY = 10
_FONT_SIZE_SMALL = 9
_LEADING_NAME = 24
_LEADING_SECTION = 16
_LEADING_BODY = 14
_LEADING_SMALL = 13
_SECTION_SPACE_BEFORE = 14
_SECTION_SPACE_AFTER = 4
_BULLET_INDENT = 14


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def generate_cv_pdf(
    application_id: int,
    adapted_cv: dict,
    cv_profile: str,
) -> Path:
    """
    Render the adapted CV JSON to a clean, ATS-friendly PDF.

    Runs ReportLab in a thread executor (blocking IO).
    Returns the Path to the generated PDF.
    """
    out_dir = CV_GENERATED_DIR / str(application_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / "cv.pdf"

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, _generate_pdf_sync, adapted_cv, str(pdf_path)
    )

    log.info(
        "cv_generator.generated",
        application_id=application_id,
        cv_profile=cv_profile,
        pdf_path=str(pdf_path),
        file_size_kb=round(pdf_path.stat().st_size / 1024, 1),
    )
    return pdf_path


# ---------------------------------------------------------------------------
# Synchronous ReportLab rendering (runs in thread executor)
# ---------------------------------------------------------------------------

def _generate_pdf_sync(cv: dict, output_path: str) -> None:
    try:
        from reportlab.lib.pagesizes import A4  # type: ignore
        from reportlab.lib.units import mm  # type: ignore
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # type: ignore
        from reportlab.lib.enums import TA_LEFT, TA_CENTER  # type: ignore
        from reportlab.platypus import (  # type: ignore
            SimpleDocTemplate, Paragraph, Spacer, HRFlowable, KeepTogether,
        )
        from reportlab.lib import colors  # type: ignore
    except ImportError as e:
        raise ImportError("reportlab is required: pip install reportlab") from e

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=_PAGE_MARGIN,
        rightMargin=_PAGE_MARGIN,
        topMargin=_PAGE_MARGIN,
        bottomMargin=_PAGE_MARGIN,
        title=cv.get("name", "CV"),
        author=cv.get("name", ""),
    )

    story: list[Any] = []

    # -----------------------------------------------------------------------
    # Header: Name + contact info
    # -----------------------------------------------------------------------
    name = cv.get("name", "").strip()
    if name:
        story.append(
            Paragraph(
                name,
                ParagraphStyle(
                    "CandidateName",
                    fontName=_FONT_BOLD,
                    fontSize=_FONT_SIZE_NAME,
                    leading=_LEADING_NAME,
                    textColor=colors.Color(*_BLACK),
                    spaceAfter=4,
                ),
            )
        )

    contact_parts: list[str] = []
    if cv.get("email"):
        contact_parts.append(cv["email"])
    if cv.get("phone"):
        contact_parts.append(cv["phone"])
    if cv.get("location"):
        contact_parts.append(cv["location"])
    if cv.get("linkedin"):
        contact_parts.append(cv["linkedin"])
    if cv.get("github"):
        contact_parts.append(cv["github"])

    if contact_parts:
        story.append(
            Paragraph(
                " | ".join(contact_parts),
                ParagraphStyle(
                    "ContactLine",
                    fontName=_FONT_NAME,
                    fontSize=_FONT_SIZE_SMALL,
                    leading=_LEADING_SMALL,
                    textColor=colors.Color(*_MEDIUM_GRAY),
                    spaceAfter=6,
                ),
            )
        )

    story.append(
        HRFlowable(
            width="100%",
            thickness=1,
            color=colors.Color(*_DARK_GRAY),
            spaceAfter=8,
        )
    )

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    summary = (cv.get("summary") or "").strip()
    if summary:
        story.extend(_section_header("Perfil Profesional"))
        story.append(
            Paragraph(
                summary,
                ParagraphStyle(
                    "SummaryBody",
                    fontName=_FONT_NAME,
                    fontSize=_FONT_SIZE_BODY,
                    leading=_LEADING_BODY,
                    textColor=colors.Color(*_BLACK),
                    spaceAfter=4,
                ),
            )
        )
        story.append(Spacer(1, _SECTION_SPACE_BEFORE))

    # -----------------------------------------------------------------------
    # Experience
    # -----------------------------------------------------------------------
    experience = cv.get("experience", [])
    if experience:
        story.extend(_section_header("Experiencia Laboral"))
        for exp in experience:
            story.extend(_render_experience_entry(exp, colors))

    # -----------------------------------------------------------------------
    # Skills
    # -----------------------------------------------------------------------
    skills = cv.get("skills", [])
    skills_section_text = cv.get("skills_section_text", "")
    if skills or skills_section_text:
        story.extend(_section_header("Habilidades"))
        if skills_section_text:
            skills_text = skills_section_text
        else:
            skills_text = ", ".join(skills)
        story.append(
            Paragraph(
                skills_text,
                ParagraphStyle(
                    "SkillsBody",
                    fontName=_FONT_NAME,
                    fontSize=_FONT_SIZE_BODY,
                    leading=_LEADING_BODY,
                    textColor=colors.Color(*_BLACK),
                    spaceAfter=4,
                ),
            )
        )
        story.append(Spacer(1, _SECTION_SPACE_BEFORE))

    # -----------------------------------------------------------------------
    # Education
    # -----------------------------------------------------------------------
    education = cv.get("education", [])
    if education:
        story.extend(_section_header("Educación"))
        for edu in education:
            story.extend(_render_education_entry(edu, colors))

    # -----------------------------------------------------------------------
    # Languages
    # -----------------------------------------------------------------------
    languages = cv.get("languages", [])
    if languages:
        story.extend(_section_header("Idiomas"))
        lang_parts: list[str] = []
        for lang in languages:
            if isinstance(lang, dict):
                name_l = lang.get("language", "")
                level = lang.get("level", "")
                if name_l and level:
                    lang_parts.append(f"{name_l}: {level}")
                elif name_l:
                    lang_parts.append(name_l)
            elif isinstance(lang, str):
                lang_parts.append(lang)
        if lang_parts:
            story.append(
                Paragraph(
                    " | ".join(lang_parts),
                    ParagraphStyle(
                        "LanguagesBody",
                        fontName=_FONT_NAME,
                        fontSize=_FONT_SIZE_BODY,
                        leading=_LEADING_BODY,
                        textColor=colors.Color(*_BLACK),
                        spaceAfter=4,
                    ),
                )
            )
        story.append(Spacer(1, _SECTION_SPACE_BEFORE))

    # -----------------------------------------------------------------------
    # Certifications
    # -----------------------------------------------------------------------
    certifications = cv.get("certifications", [])
    if certifications:
        story.extend(_section_header("Certificaciones"))
        for cert in certifications:
            if isinstance(cert, str) and cert.strip():
                story.append(
                    Paragraph(
                        f"• {cert.strip()}",
                        ParagraphStyle(
                            "CertBullet",
                            fontName=_FONT_NAME,
                            fontSize=_FONT_SIZE_BODY,
                            leading=_LEADING_BODY,
                            leftIndent=_BULLET_INDENT,
                            textColor=colors.Color(*_BLACK),
                            spaceAfter=2,
                        ),
                    )
                )
        story.append(Spacer(1, _SECTION_SPACE_BEFORE))

    doc.build(story)


# ---------------------------------------------------------------------------
# Section building helpers
# ---------------------------------------------------------------------------

def _section_header(title: str) -> list[Any]:
    """Return [Spacer, Header Paragraph, thin HR, small spacer]."""
    try:
        from reportlab.platypus import Spacer, Paragraph, HRFlowable  # type: ignore
        from reportlab.lib.styles import ParagraphStyle  # type: ignore
        from reportlab.lib import colors  # type: ignore
    except ImportError:
        return []

    return [
        Spacer(1, _SECTION_SPACE_BEFORE),
        Paragraph(
            title.upper(),
            ParagraphStyle(
                f"SectionHeader_{title}",
                fontName=_FONT_BOLD,
                fontSize=_FONT_SIZE_SECTION,
                leading=_LEADING_SECTION,
                textColor=colors.Color(*_DARK_GRAY),
                spaceAfter=2,
            ),
        ),
        HRFlowable(
            width="100%",
            thickness=0.5,
            color=colors.Color(*_LIGHT_GRAY),
            spaceAfter=_SECTION_SPACE_AFTER,
        ),
    ]


def _render_experience_entry(exp: dict, colors: Any) -> list[Any]:
    """Render a single experience entry as a list of Flowables."""
    try:
        from reportlab.platypus import Spacer, Paragraph, KeepTogether  # type: ignore
        from reportlab.lib.styles import ParagraphStyle  # type: ignore
    except ImportError:
        return []

    items: list[Any] = []

    company = (exp.get("company") or "").strip()
    title = (exp.get("title") or "").strip()
    start_date = (exp.get("start_date") or "").strip()
    end_date = (exp.get("end_date") or "").strip()

    date_str = ""
    if start_date and end_date:
        date_str = f"{start_date} – {end_date}"
    elif start_date:
        date_str = start_date

    # Company + dates on the same line (bold company, gray dates)
    if company and date_str:
        header_text = (
            f'<b>{_escape_xml(company)}</b>'
            f'<font color="#737373" size="{_FONT_SIZE_SMALL}">    {_escape_xml(date_str)}</font>'
        )
    elif company:
        header_text = f"<b>{_escape_xml(company)}</b>"
    elif date_str:
        header_text = f'<font color="#737373">{_escape_xml(date_str)}</font>'
    else:
        header_text = ""

    if header_text:
        items.append(
            Paragraph(
                header_text,
                ParagraphStyle(
                    "ExpCompany",
                    fontName=_FONT_BOLD,
                    fontSize=_FONT_SIZE_BODY,
                    leading=_LEADING_BODY,
                    textColor=colors.Color(*_BLACK),
                    spaceAfter=1,
                ),
            )
        )

    # Job title (bold, slightly smaller)
    if title:
        items.append(
            Paragraph(
                f"<b>{_escape_xml(title)}</b>",
                ParagraphStyle(
                    "ExpTitle",
                    fontName=_FONT_BOLD,
                    fontSize=_FONT_SIZE_BODY,
                    leading=_LEADING_BODY,
                    textColor=colors.Color(*_DARK_GRAY),
                    spaceAfter=2,
                ),
            )
        )

    # Bullet points
    bullet_style = ParagraphStyle(
        "ExpBullet",
        fontName=_FONT_NAME,
        fontSize=_FONT_SIZE_BODY,
        leading=_LEADING_BODY,
        leftIndent=_BULLET_INDENT,
        textColor=colors.Color(*_BLACK),
        spaceAfter=2,
    )
    for bullet in exp.get("bullets", []):
        if isinstance(bullet, str) and bullet.strip():
            items.append(
                Paragraph(f"• {_escape_xml(bullet.strip())}", bullet_style)
            )

    items.append(Spacer(1, 6))

    # Keep company header + title + first bullet together on same page
    if len(items) >= 2:
        keep = items[:min(3, len(items))]
        rest = items[min(3, len(items)):]
        return [KeepTogether(keep)] + rest

    return items


def _render_education_entry(edu: dict, colors: Any) -> list[Any]:
    """Render a single education entry."""
    try:
        from reportlab.platypus import Spacer, Paragraph  # type: ignore
        from reportlab.lib.styles import ParagraphStyle  # type: ignore
    except ImportError:
        return []

    items: list[Any] = []

    institution = (edu.get("institution") or "").strip()
    degree = (edu.get("degree") or "").strip()
    year = (edu.get("year") or "").strip()

    if degree and year:
        header_text = (
            f'<b>{_escape_xml(degree)}</b>'
            f'<font color="#737373" size="{_FONT_SIZE_SMALL}">    {_escape_xml(year)}</font>'
        )
    elif degree:
        header_text = f"<b>{_escape_xml(degree)}</b>"
    else:
        header_text = ""

    if header_text:
        items.append(
            Paragraph(
                header_text,
                ParagraphStyle(
                    "EduDegree",
                    fontName=_FONT_BOLD,
                    fontSize=_FONT_SIZE_BODY,
                    leading=_LEADING_BODY,
                    textColor=colors.Color(*_BLACK),
                    spaceAfter=1,
                ),
            )
        )

    if institution:
        items.append(
            Paragraph(
                _escape_xml(institution),
                ParagraphStyle(
                    "EduInstitution",
                    fontName=_FONT_NAME,
                    fontSize=_FONT_SIZE_SMALL,
                    leading=_LEADING_SMALL,
                    textColor=colors.Color(*_MEDIUM_GRAY),
                    spaceAfter=4,
                ),
            )
        )

    items.append(Spacer(1, 4))
    return items


def _escape_xml(text: str) -> str:
    """Escape XML special characters for ReportLab Paragraph markup."""
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
    )
