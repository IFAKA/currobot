"""Lever ATS platform scraper — pure httpx."""
from __future__ import annotations

import hashlib
from typing import Any, Optional

import httpx
import structlog

from backend.scrapers.base import BaseScraper

log = structlog.get_logger(__name__)

SPAIN_KEYWORDS = [
    "spain", "españa", "madrid", "barcelona", "remote", "remoto",
    "híbrido", "hibrido", "valencia", "sevilla", "bilbao", "zaragoza",
    "anywhere", "worldwide",
]

# Spanish tech companies using Lever ATS
DEFAULT_COMPANIES: dict[str, str] = {
    "cabify": "fullstack_dev",
    "schibsted-spain": "fullstack_dev",
    "idealista": "fullstack_dev",
    "flywire": "fullstack_dev",
    "privalia": "fullstack_dev",
    "ulabox": "fullstack_dev",
    "bcneng": "fullstack_dev",
    "fever": "fullstack_dev",
    "adevinta": "fullstack_dev",
    "lastminute-com": "fullstack_dev",
}


class LeverScraper(BaseScraper):
    """Scrape Lever ATS job boards for Spanish tech companies."""

    SITE = "lever"
    API_BASE = "https://api.lever.co/v0/postings/{company}?mode=json"

    HEADERS = {
        "Accept": "application/json",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    }

    def __init__(self, db_session_factory: Any) -> None:
        super().__init__(self.SITE, db_session_factory)

    # ------------------------------------------------------------------
    # Main scrape
    # ------------------------------------------------------------------

    async def scrape(self) -> list[dict]:
        companies = dict(DEFAULT_COMPANIES)

        # Merge with DB-configured sources
        try:
            async with self.db_session_factory() as db:
                from backend.database.crud import list_company_sources
                sources = await list_company_sources(db, enabled_only=True)
                for source in sources:
                    if source.scraper_type == "lever":
                        extra = source.extra_config or {}
                        slug = extra.get("slug") or source.company_name.lower().replace(" ", "-")
                        companies[slug] = source.cv_profile
        except Exception as exc:
            self._log.warning("lever.db_sources_error", error=str(exc))

        all_jobs: list[dict] = []

        async with httpx.AsyncClient(
            headers=self.HEADERS,
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            for company_slug, cv_profile in companies.items():
                self._log.info("lever.fetching", company=company_slug)
                jobs = await self._fetch_company(client, company_slug, cv_profile)
                all_jobs.extend(jobs)
                self._log.info("lever.company_done", company=company_slug, found=len(jobs))
                await self._rate_limit()

        # Deduplicate
        seen: set[str] = set()
        unique: list[dict] = []
        for job in all_jobs:
            eid = job.get("external_id", "")
            if eid not in seen:
                seen.add(eid)
                unique.append(job)

        self._log.info("lever.total", total=len(unique))
        return unique

    # ------------------------------------------------------------------
    # Per-company fetch
    # ------------------------------------------------------------------

    async def _fetch_company(
        self, client: httpx.AsyncClient, company: str, cv_profile: str
    ) -> list[dict]:
        url = self.API_BASE.format(company=company)
        try:
            resp = await client.get(url, timeout=20.0)
            if resp.status_code == 404:
                self._log.debug("lever.company_not_found", company=company)
                return []
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            self._log.warning(
                "lever.http_error",
                company=company,
                status=exc.response.status_code,
                error=str(exc),
            )
            return []
        except Exception as exc:
            self._log.warning("lever.fetch_error", company=company, error=str(exc))
            return []

        if not isinstance(data, list):
            data = data.get("jobs") or data.get("postings") or [] if isinstance(data, dict) else []

        result: list[dict] = []
        for raw in data:
            if not isinstance(raw, dict):
                continue
            # Filter for Spain/Remote
            categories = raw.get("categories") or {}
            location = ""
            if isinstance(categories, dict):
                location = categories.get("location") or categories.get("region") or ""
            elif isinstance(categories, list):
                for cat in categories:
                    if isinstance(cat, dict) and cat.get("name") == "Location":
                        location = cat.get("value", "")
                        break

            if location and not self._is_spain_or_remote(location):
                continue

            job = self._normalise_job(raw, company, cv_profile, location)
            if job:
                result.append(job)

        return result

    # ------------------------------------------------------------------
    # Normalisation
    # ------------------------------------------------------------------

    def _normalise_job(
        self, raw: dict, company: str, cv_profile: str, location: str
    ) -> Optional[dict]:
        external_id = str(raw.get("id") or "")
        if not external_id:
            return None

        title = raw.get("text") or raw.get("title") or ""
        company_name = raw.get("company") or self._slug_to_company_name(company)

        url = raw.get("hostedUrl") or raw.get("applyUrl") or f"https://jobs.lever.co/{company}/{external_id}"

        # Extract description
        description_list = raw.get("descriptionPlain") or raw.get("description") or ""
        if isinstance(description_list, list):
            description = "\n".join(str(x) for x in description_list)
        else:
            description = str(description_list)

        # Categories
        categories = raw.get("categories") or {}
        team = ""
        if isinstance(categories, dict):
            team = categories.get("team") or categories.get("department") or ""

        refined_profile = self._assign_cv_profile(title, cv_profile)

        return {
            "site": self.SITE,
            "external_id": f"{company}_{external_id}",
            "url": url,
            "title": title,
            "company": company_name,
            "location": location or "España",
            "description": description,
            "salary_raw": None,
            "contract_type": raw.get("workplaceType") or team or None,
            "cv_profile": refined_profile,
            "raw_data": raw,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_spain_or_remote(self, location: str) -> bool:
        loc = location.lower()
        return any(kw in loc for kw in SPAIN_KEYWORDS) or not loc

    def _slug_to_company_name(self, slug: str) -> str:
        known = {
            "cabify": "Cabify",
            "schibsted-spain": "Schibsted Spain",
            "idealista": "Idealista",
            "flywire": "Flywire",
            "privalia": "Privalia",
            "ulabox": "Ulabox",
            "bcneng": "BCN Engineering",
            "fever": "Fever",
            "adevinta": "Adevinta",
            "lastminute-com": "Lastminute.com",
        }
        return known.get(slug, slug.replace("-", " ").title())

    def _assign_cv_profile(self, title: str, default: str) -> str:
        t = title.lower()
        if any(kw in t for kw in ["frontend", "front-end", "react", "vue", "angular", "ui engineer"]):
            return "frontend_dev"
        if any(kw in t for kw in ["fullstack", "full stack", "full-stack", "backend", "software engineer", "developer", "python", "java", "node", "sre", "devops"]):
            return "fullstack_dev"
        return default
