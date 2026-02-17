"""Greenhouse ATS platform scraper — pure httpx, no browser needed."""
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
]

# Default company slugs and the CV profile they map to.
# All are Spanish-based or have significant Spain presence.
DEFAULT_COMPANIES: dict[str, str] = {
    "cabify": "fullstack_dev",
    "glovo": "fullstack_dev",
    "wallapop": "fullstack_dev",
    "travelperk": "frontend_dev",
    "typeform": "frontend_dev",
    "factorial": "fullstack_dev",
    "paack": "fullstack_dev",
    "jobandtalent": "fullstack_dev",
    "letgo": "fullstack_dev",
    "habitissimo": "fullstack_dev",
}


class GreenhouseScraper(BaseScraper):
    """Scrape Greenhouse ATS job boards for Spanish tech companies."""

    SITE = "greenhouse"
    API_BASE = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"

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
        # Merge DEFAULT_COMPANIES with any DB-configured sources
        companies = dict(DEFAULT_COMPANIES)
        try:
            async with self.db_session_factory() as db:
                from backend.database.crud import list_company_sources
                sources = await list_company_sources(db, enabled_only=True)
                for source in sources:
                    if source.scraper_type == "greenhouse":
                        extra = source.extra_config or {}
                        slug = extra.get("slug") or source.company_name.lower().replace(" ", "")
                        companies[slug] = source.cv_profile
        except Exception as exc:
            self._log.warning("greenhouse.db_sources_error", error=str(exc))

        all_jobs: list[dict] = []

        async with httpx.AsyncClient(
            headers=self.HEADERS,
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            for slug, cv_profile in companies.items():
                self._log.info("greenhouse.fetching", slug=slug)
                jobs = await self._fetch_company(client, slug, cv_profile)
                all_jobs.extend(jobs)
                self._log.info("greenhouse.company_done", slug=slug, found=len(jobs))
                await self._rate_limit()

        # Deduplicate
        seen: set[str] = set()
        unique: list[dict] = []
        for job in all_jobs:
            eid = job.get("external_id", "")
            if eid not in seen:
                seen.add(eid)
                unique.append(job)

        self._log.info("greenhouse.total", total=len(unique))
        return unique

    # ------------------------------------------------------------------
    # Per-company fetch
    # ------------------------------------------------------------------

    async def _fetch_company(
        self, client: httpx.AsyncClient, slug: str, cv_profile: str
    ) -> list[dict]:
        url = self.API_BASE.format(slug=slug)
        try:
            resp = await client.get(url, timeout=20.0)
            if resp.status_code == 404:
                self._log.debug("greenhouse.company_not_found", slug=slug)
                return []
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            self._log.warning(
                "greenhouse.http_error",
                slug=slug,
                status=exc.response.status_code,
                error=str(exc),
            )
            return []
        except Exception as exc:
            self._log.warning("greenhouse.fetch_error", slug=slug, error=str(exc))
            return []

        jobs_raw = data.get("jobs") if isinstance(data, dict) else (data if isinstance(data, list) else [])
        result: list[dict] = []
        for raw in jobs_raw:
            if not isinstance(raw, dict):
                continue
            # Filter for Spain/Remote
            location_name = (raw.get("location") or {}).get("name", "") if isinstance(raw.get("location"), dict) else str(raw.get("location") or "")
            if not self._is_spain_or_remote(location_name):
                continue
            job = self._normalise_job(raw, slug, cv_profile)
            if job:
                result.append(job)

        return result

    # ------------------------------------------------------------------
    # Normalisation
    # ------------------------------------------------------------------

    def _normalise_job(self, raw: dict, company_slug: str, cv_profile: str) -> Optional[dict]:
        external_id = str(raw.get("id") or raw.get("gh_Id") or "")
        if not external_id:
            return None

        title = raw.get("title") or ""
        company = self._slug_to_company_name(company_slug)

        location_node = raw.get("location") or {}
        location = (
            location_node.get("name") if isinstance(location_node, dict) else str(location_node)
        ) or "España"

        url = raw.get("absolute_url") or f"https://boards.greenhouse.io/{company_slug}/jobs/{external_id}"
        description = raw.get("content") or raw.get("metadata") or ""

        # Refine cv_profile based on title
        refined_profile = self._assign_cv_profile(title, cv_profile)

        return {
            "site": self.SITE,
            "external_id": f"{company_slug}_{external_id}",
            "url": url,
            "title": title,
            "company": company,
            "location": location,
            "description": description,
            "salary_raw": None,
            "contract_type": None,
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
        """Convert slug like 'travelperk' → 'TravelPerk'."""
        known = {
            "cabify": "Cabify",
            "glovo": "Glovo",
            "wallapop": "Wallapop",
            "travelperk": "TravelPerk",
            "typeform": "Typeform",
            "factorial": "Factorial",
            "paack": "Paack",
            "jobandtalent": "Job&Talent",
            "letgo": "Letgo",
            "habitissimo": "Habitissimo",
        }
        return known.get(slug, slug.capitalize())

    def _assign_cv_profile(self, title: str, default: str) -> str:
        t = title.lower()
        if any(kw in t for kw in ["frontend", "front-end", "react", "vue", "angular", "css", "ui engineer"]):
            return "frontend_dev"
        if any(kw in t for kw in ["fullstack", "full stack", "full-stack", "backend", "software engineer", "developer", "python", "java", "node"]):
            return "fullstack_dev"
        return default
