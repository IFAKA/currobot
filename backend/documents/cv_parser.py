"""PDF → canonical JSON CV parser using pdfplumber."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Section header patterns (Spanish + English)
# ---------------------------------------------------------------------------

_SECTION_HEADERS: dict[str, list[str]] = {
    "experience": [
        "experiencia", "experience", "experiencia laboral",
        "experiencia profesional", "work experience", "employment history",
        "historial laboral", "trayectoria profesional",
    ],
    "education": [
        "educación", "education", "formación", "formación académica",
        "estudios", "academic background", "titulación",
    ],
    "skills": [
        "habilidades", "skills", "competencias", "conocimientos",
        "tecnologías", "technologies", "tech stack", "hard skills",
        "soft skills", "aptitudes",
    ],
    "languages": [
        "idiomas", "languages", "lenguas", "language skills",
    ],
    "summary": [
        "resumen", "summary", "perfil", "profile", "sobre mí", "about me",
        "objetivo", "objective", "presentación",
    ],
    "certifications": [
        "certificaciones", "certifications", "certificados", "certificates",
        "cursos", "courses", "formación complementaria",
    ],
    "projects": [
        "proyectos", "projects", "portfolio",
    ],
}

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_PHONE_ES_RE = re.compile(
    r"(?:\+34[\s\-]?)?(?:\d{3}[\s\-]?\d{3}[\s\-]?\d{3}|\d{9})"
)
_LINKEDIN_RE = re.compile(
    r"(?:https?://)?(?:www\.)?linkedin\.com/in/([\w\-]+)", re.IGNORECASE
)
_GITHUB_RE = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/([\w\-]+)", re.IGNORECASE
)
_DATE_RE = re.compile(
    r"(?:"
    r"(?:ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic"
    r"|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
    r"\.?\s+\d{4}"
    r"|(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre"
    r"|january|february|march|april|may|june|july|august|september|october|november|december)"
    r"\s+\d{4}"
    r"|\d{1,2}/\d{4}"
    r"|\d{4}"
    r")",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_DATE_RANGE_RE = re.compile(
    r"([\w\./ ]+\d{4})\s*[-–—]\s*([\w\./ ]+\d{4}|[Pp]resente|[Aa]ctual|[Cc]urrent|[Pp]resent|[Hh]oy)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def parse_cv(pdf_path: Path) -> dict:
    """
    Parse a PDF CV into the canonical JSON structure.

    Runs pdfplumber in a thread executor to avoid blocking the event loop.

    Returns:
        {
            "name": str,
            "email": str,
            "phone": str,
            "location": str,
            "linkedin": str,
            "github": str,
            "summary": str,
            "experience": [{"company": str, "title": str, "start_date": str,
                            "end_date": str, "bullets": [str]}],
            "education": [{"institution": str, "degree": str, "year": str}],
            "skills": [str],
            "languages": [{"language": str, "level": str}],
            "certifications": [str],
            "raw_text": str,
        }
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"CV PDF not found: {pdf_path}")

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _parse_pdf_sync, pdf_path)

    log.info(
        "cv_parser.parsed",
        path=str(pdf_path),
        name=result.get("name"),
        experience_entries=len(result.get("experience", [])),
        skills_count=len(result.get("skills", [])),
    )
    return result


# ---------------------------------------------------------------------------
# Synchronous parsing (runs in thread executor)
# ---------------------------------------------------------------------------

def _parse_pdf_sync(pdf_path: Path) -> dict:
    try:
        import pdfplumber  # type: ignore
    except ImportError as e:
        raise ImportError("pdfplumber is required: pip install pdfplumber") from e

    pages_text: list[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text(x_tolerance=3, y_tolerance=3)
            if text:
                pages_text.append(text)

    full_text = "\n".join(pages_text)
    lines = [line.strip() for line in full_text.splitlines() if line.strip()]

    canonical = _extract_all(lines, full_text)
    canonical["raw_text"] = full_text
    return canonical


def _extract_all(lines: list[str], full_text: str) -> dict:
    sections = _split_into_sections(lines)

    result: dict = {
        "name": "",
        "email": "",
        "phone": "",
        "location": "",
        "linkedin": "",
        "github": "",
        "summary": "",
        "experience": [],
        "education": [],
        "skills": [],
        "languages": [],
        "certifications": [],
    }

    # PII extraction from full text
    result["email"] = _extract_email(full_text)
    result["phone"] = _extract_phone(full_text)
    result["linkedin"] = _extract_linkedin(full_text)
    result["github"] = _extract_github(full_text)
    result["name"] = _extract_name(lines)
    result["location"] = _extract_location(lines, result["email"], result["phone"])

    # Section-based extraction
    if "summary" in sections:
        result["summary"] = " ".join(sections["summary"]).strip()

    if "experience" in sections:
        result["experience"] = _parse_experience(sections["experience"])

    if "education" in sections:
        result["education"] = _parse_education(sections["education"])

    if "skills" in sections:
        result["skills"] = _parse_skills(sections["skills"])

    if "languages" in sections:
        result["languages"] = _parse_languages(sections["languages"])

    if "certifications" in sections:
        result["certifications"] = [
            line for line in sections["certifications"] if len(line) > 3
        ]

    return result


# ---------------------------------------------------------------------------
# Section splitter
# ---------------------------------------------------------------------------

def _split_into_sections(lines: list[str]) -> dict[str, list[str]]:
    """
    Split lines into named sections by detecting section headers.
    Returns a dict mapping section_key → list of content lines.
    """
    sections: dict[str, list[str]] = {}
    current_section: Optional[str] = None
    header_lines: list[str] = []

    for line in lines:
        section_key = _identify_section_header(line)
        if section_key:
            current_section = section_key
            sections[current_section] = []
            header_lines.append(line)
        elif current_section is not None:
            sections[current_section].append(line)

    return sections


def _identify_section_header(line: str) -> Optional[str]:
    """Return section key if the line looks like a section header, else None."""
    clean = line.lower().strip().rstrip(":")
    # Must be reasonably short to be a header (not a full sentence)
    if len(clean.split()) > 5:
        return None
    for section_key, patterns in _SECTION_HEADERS.items():
        if clean in patterns:
            return section_key
    return None


# ---------------------------------------------------------------------------
# PII extractors
# ---------------------------------------------------------------------------

def _extract_email(text: str) -> str:
    match = _EMAIL_RE.search(text)
    return match.group(0) if match else ""


def _extract_phone(text: str) -> str:
    match = _PHONE_ES_RE.search(text)
    if match:
        phone = re.sub(r"[\s\-]", "", match.group(0))
        # Normalise to +34 format if looks like Spanish mobile/landline
        if len(phone) == 9 and phone[0] in "6789":
            return f"+34 {phone[:3]} {phone[3:6]} {phone[6:]}"
        return match.group(0)
    return ""


def _extract_linkedin(text: str) -> str:
    match = _LINKEDIN_RE.search(text)
    if match:
        return f"https://linkedin.com/in/{match.group(1)}"
    return ""


def _extract_github(text: str) -> str:
    match = _GITHUB_RE.search(text)
    if match:
        username = match.group(1)
        # Exclude common non-username paths
        if username.lower() not in ("features", "pricing", "about", "login", "signup"):
            return f"https://github.com/{username}"
    return ""


def _extract_name(lines: list[str]) -> str:
    """
    Heuristic: the name is usually on the first non-empty line,
    is title-cased, contains no digits, and is 2-5 words.
    """
    for line in lines[:5]:
        clean = line.strip()
        if not clean:
            continue
        # Skip lines that look like contact info
        if _EMAIL_RE.search(clean) or _PHONE_ES_RE.search(clean):
            continue
        if "linkedin" in clean.lower() or "github" in clean.lower():
            continue
        words = clean.split()
        if 2 <= len(words) <= 5 and not any(char.isdigit() for char in clean):
            # Check that it looks like a proper name (each word capitalized or all caps)
            if all(w[0].isupper() for w in words if w):
                return clean
    # Fallback: return first line
    return lines[0].strip() if lines else ""


def _extract_location(
    lines: list[str], email: str, phone: str
) -> str:
    """
    Look for a location in the first 10 lines.
    Heuristic: a line that is not email/phone/linkedin/github and contains
    a known Spanish city or a comma-separated place name.
    """
    spanish_cities = {
        "madrid", "barcelona", "valencia", "sevilla", "seville", "bilbao",
        "málaga", "malaga", "alicante", "granada", "murcia", "palma",
        "las palmas", "santander", "pamplona", "san sebastián", "donostia",
        "vitoria", "gasteiz", "zaragoza", "valladolid", "córdoba", "cordoba",
        "vigo", "gijón", "gijon", "hospitalet", "badalona", "terrassa",
        "sabadell", "jerez", "cartagena", "alcalá", "almería", "almeria",
    }
    for line in lines[:15]:
        clean = line.strip().lower()
        if not clean or email.lower() in clean or phone in clean:
            continue
        if "linkedin" in clean or "github" in clean or "@" in clean:
            continue
        for city in spanish_cities:
            if city in clean:
                return line.strip()
        # Look for patterns like "City, Country" or "City, Province"
        if re.match(r"^[A-ZÀ-Ú][a-zA-ZÀ-ú\s]+,\s*[A-ZÀ-Ú][a-zA-ZÀ-ú\s]+$", line.strip()):
            return line.strip()
    return ""


# ---------------------------------------------------------------------------
# Experience parser
# ---------------------------------------------------------------------------

def _parse_experience(lines: list[str]) -> list[dict]:
    entries: list[dict] = []
    current: Optional[dict] = None

    for line in lines:
        # Detect a date range — signals start of a new experience entry
        date_match = _DATE_RANGE_RE.search(line)
        if date_match:
            if current:
                entries.append(current)
            start_date = date_match.group(1).strip()
            end_date = date_match.group(2).strip()
            # Remove the date from the line to get company/title info
            remainder = _DATE_RANGE_RE.sub("", line).strip(" -–—|·•").strip()
            current = {
                "company": "",
                "title": "",
                "start_date": start_date,
                "end_date": end_date,
                "bullets": [],
                "_remainder": remainder,
            }
            continue

        if current is None:
            # Before any date — might be company/title lines
            current = {
                "company": "",
                "title": "",
                "start_date": "",
                "end_date": "",
                "bullets": [],
                "_remainder": "",
            }

        # Determine if this is company/title metadata or a bullet point
        is_bullet = line.startswith(("•", "-", "·", "–", "▪", "*", "○", "◦"))
        clean = line.lstrip("•-·–▪*○◦").strip()

        if not current["company"] and not is_bullet and len(clean) < 80:
            current["company"] = clean
        elif not current["title"] and not is_bullet and len(clean) < 100:
            current["title"] = clean
        elif clean:
            current["bullets"].append(clean)

    if current and (current["company"] or current["title"] or current["bullets"]):
        # Clean up internal key
        current.pop("_remainder", None)
        entries.append(current)

    # Clean up _remainder from all entries
    for e in entries:
        e.pop("_remainder", None)

    return entries


# ---------------------------------------------------------------------------
# Education parser
# ---------------------------------------------------------------------------

def _parse_education(lines: list[str]) -> list[dict]:
    entries: list[dict] = []
    current: Optional[dict] = None

    for line in lines:
        year_match = _YEAR_RE.search(line)
        is_bullet = line.startswith(("•", "-", "·", "–", "▪", "*"))
        clean = line.lstrip("•-·–▪*").strip()

        if not clean:
            continue

        if year_match and not is_bullet:
            if current:
                entries.append(current)
            year = year_match.group(0)
            label = _YEAR_RE.sub("", line).strip(" -–—|·•/").strip()
            current = {"institution": "", "degree": label, "year": year}
        elif current is not None:
            if not current["institution"] and len(clean) < 120:
                current["institution"] = clean
        else:
            if len(clean) < 120:
                current = {"institution": "", "degree": clean, "year": ""}

    if current and (current["institution"] or current["degree"]):
        entries.append(current)

    return entries


# ---------------------------------------------------------------------------
# Skills parser
# ---------------------------------------------------------------------------

def _parse_skills(lines: list[str]) -> list[str]:
    skills: list[str] = []
    for line in lines:
        clean = line.lstrip("•-·–▪*○◦").strip()
        if not clean:
            continue
        # Try comma-separated list first
        if "," in clean:
            skills.extend(s.strip() for s in clean.split(",") if s.strip())
        elif "|" in clean:
            skills.extend(s.strip() for s in clean.split("|") if s.strip())
        elif "/" in clean and len(clean) < 80:
            skills.extend(s.strip() for s in clean.split("/") if s.strip())
        else:
            # Individual skill or short phrase
            if len(clean) < 60:
                skills.append(clean)

    # Deduplicate preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for s in skills:
        lower = s.lower()
        if lower not in seen:
            seen.add(lower)
            unique.append(s)

    return unique


# ---------------------------------------------------------------------------
# Languages parser
# ---------------------------------------------------------------------------

_LANGUAGE_LEVELS = re.compile(
    r"(nativo|native|bilingüe|bilingual|avanzado|advanced|"
    r"intermedio|intermediate|básico|basic|elemental|"
    r"c2|c1|b2|b1|a2|a1|fluent|fluido|profesional|professional)",
    re.IGNORECASE,
)


def _parse_languages(lines: list[str]) -> list[dict]:
    languages: list[dict] = []
    for line in lines:
        clean = line.lstrip("•-·–▪*").strip()
        if not clean:
            continue
        level_match = _LANGUAGE_LEVELS.search(clean)
        if level_match:
            level = level_match.group(0)
            name = _LANGUAGE_LEVELS.sub("", clean).strip(" -–:,|").strip()
            if name:
                languages.append({"language": name, "level": level})
        else:
            # Best effort: treat the whole line as language name, no level
            if len(clean) < 40:
                languages.append({"language": clean, "level": ""})

    return languages
