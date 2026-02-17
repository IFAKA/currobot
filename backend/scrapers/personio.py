"""Personio ATS platform scraper — httpx with JSON-first, HTML fallback."""
from __future__ import annotations

import hashlib
from typing import Any, Optional
from urllib.parse import urljoin

import httpx
import structlog

from backend.scrapers.base import BaseScraper

log = structlog.get_logger(__name__)

# Spanish companies and SMEs known to use Personio
DEFAULT_COMPANIES: dict[str, dict[str, str]] = {
    "holded": {"cv_profile": "fullstack_dev", "name": "Holded"},
    "factorial": {"cv_profile": "fullstack_dev", "name": "Factorial HR"},
    "leasys": {"cv_profile": "fullstack_dev", "name": "Leasys"},
    "mango": {"cv_profile": "logistics", "name": "Mango"},
    "idealista": {"cv_profile": "fullstack_dev", "name": "Idealista"},
    "flywire": {"cv_profile": "fullstack_dev", "name": "Flywire"},
    "amenitiz": {"cv_profile": "fullstack_dev", "name": "Amenitiz"},
    "carto": {"cv_profile": "fullstack_dev", "name": "CARTO"},
    "colvin": {"cv_profile": "logistics", "name": "Colvin"},
    "jobandtalent": {"cv_profile": "fullstack_dev", "name": "Job&Talent"},
}


class PersonioScraper(BaseScraper):
    """Scrape Personio-hosted career pages for Spanish companies."""

    SITE = "personio"
    API_BASE = "https://{company}.jobs.personio.com/job-descriptions"
    PUBLIC_PAGE = "https://{company}.jobs.personio.com"

    HEADERS = {
        "Accept": "application/json, text/html, */*",
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
                    if source.scraper_type == "personio":
                        extra = source.extra_config or {}
                        slug = extra.get("slug") or source.company_name.lower().replace(" ", "")
                        companies[slug] = {
                            "cv_profile": source.cv_profile,
                            "name": source.company_name,
                        }
        except Exception as exc:
            self._log.warning("personio.db_sources_error", error=str(exc))

        all_jobs: list[dict] = []

        async with httpx.AsyncClient(
            headers=self.HEADERS,
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            for slug, meta in companies.items():
                cv_profile = meta.get("cv_profile", "fullstack_dev")
                company_name = meta.get("name", slug.capitalize())
                self._log.info("personio.fetching", slug=slug)
                jobs = await self._fetch_company(client, slug, cv_profile, company_name)
                all_jobs.extend(jobs)
                self._log.info("personio.company_done", slug=slug, found=len(jobs))
                await self._rate_limit()

        # Deduplicate
        seen: set[str] = set()
        unique: list[dict] = []
        for job in all_jobs:
            eid = job.get("external_id", "")
            if eid not in seen:
                seen.add(eid)
                unique.append(job)

        self._log.info("personio.total", total=len(unique))
        return unique

    # ------------------------------------------------------------------
    # Per-company fetch
    # ------------------------------------------------------------------

    async def _fetch_company(
        self, client: httpx.AsyncClient, slug: str, cv_profile: str, company_name: str
    ) -> list[dict]:
        jobs: list[dict] = []

        # Strategy 1: JSON API endpoint
        api_url = self.API_BASE.format(company=slug)
        try:
            resp = await client.get(
                api_url,
                headers={**self.HEADERS, "Accept": "application/json"},
                timeout=20.0,
            )
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    jobs = self._parse_json_response(data, slug, cv_profile, company_name)
                    if jobs:
                        self._log.debug("personio.json_success", slug=slug, count=len(jobs))
                        return jobs
                except Exception as exc:
                    self._log.debug("personio.json_parse_error", slug=slug, error=str(exc))
        except Exception as exc:
            self._log.debug("personio.json_fetch_error", slug=slug, error=str(exc))

        # Strategy 2: HTML page scrape
        page_url = self.PUBLIC_PAGE.format(company=slug)
        try:
            resp = await client.get(page_url, timeout=20.0)
            if resp.status_code == 200:
                jobs = self._parse_html_response(resp.text, slug, cv_profile, company_name, page_url)
                self._log.debug("personio.html_fallback", slug=slug, count=len(jobs))
        except Exception as exc:
            self._log.warning("personio.html_fetch_error", slug=slug, error=str(exc))

        return jobs

    # ------------------------------------------------------------------
    # JSON response parser
    # ------------------------------------------------------------------

    def _parse_json_response(
        self, data: Any, slug: str, cv_profile: str, company_name: str
    ) -> list[dict]:
        raw_list: list[dict] = []

        if isinstance(data, dict):
            raw_list = (
                data.get("jobs")
                or data.get("jobDescriptions")
                or data.get("job_descriptions")
                or data.get("data")
                or []
            )
        elif isinstance(data, list):
            raw_list = data

        result: list[dict] = []
        for raw in raw_list:
            if not isinstance(raw, dict):
                continue
            job = self._normalise_json_job(raw, slug, cv_profile, company_name)
            if job:
                result.append(job)
        return result

    def _normalise_json_job(
        self, raw: dict, slug: str, cv_profile: str, company_name: str
    ) -> Optional[dict]:
        external_id = str(
            raw.get("jobDescriptionId")
            or raw.get("id")
            or raw.get("jobId")
            or ""
        )
        if not external_id:
            return None

        title = raw.get("name") or raw.get("title") or raw.get("jobTitle") or ""
        location = (
            raw.get("office")
            or raw.get("location")
            or raw.get("city")
            or "España"
        )
        if isinstance(location, dict):
            location = location.get("name") or location.get("label") or "España"

        employment_type = raw.get("employmentType") or raw.get("contractType") or None
        seo_url = raw.get("seoUrl") or raw.get("slug") or external_id
        url = f"https://{slug}.jobs.personio.com/job/{seo_url}"

        description = raw.get("jobDescription") or raw.get("description") or ""

        return {
            "site": self.SITE,
            "external_id": f"{slug}_{external_id}",
            "url": url,
            "title": title,
            "company": company_name,
            "location": location,
            "description": description,
            "salary_raw": None,
            "contract_type": employment_type,
            "cv_profile": self._assign_cv_profile(title, cv_profile),
            "raw_data": raw,
        }

    # ------------------------------------------------------------------
    # HTML fallback parser
    # ------------------------------------------------------------------

    def _parse_html_response(
        self, html: str, slug: str, cv_profile: str, company_name: str, base_url: str
    ) -> list[dict]:
        jobs: list[dict] = []

        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")

            # Look for job listing elements
            selectors = [
                ".job-listing",
                "[class*='job-item']",
                "[data-job-id]",
                "li[class*='opening']",
                ".opening",
            ]
            cards = []
            for sel in selectors:
                cards = soup.select(sel)
                if cards:
                    break

            # Fallback: any link that goes to /job/
            if not cards:
                import re
                links = soup.find_all("a", href=re.compile(r"/job/"))
                for link in links:
                    title = link.get_text(strip=True)
                    href = link.get("href", "")
                    url = urljoin(base_url, href)
                    if title:
                        external_id = href.split("/")[-1] or self._synthetic_id(title, slug)
                        jobs.append({
                            "site": self.SITE,
                            "external_id": f"{slug}_{external_id}",
                            "url": url,
                            "title": title,
                            "company": company_name,
                            "location": "España",
                            "description": None,
                            "salary_raw": None,
                            "contract_type": None,
                            "cv_profile": self._assign_cv_profile(title, cv_profile),
                            "raw_data": {"title": title, "url": url},
                        })
                return jobs

            for card in cards:
                try:
                    link_el = card.find("a", href=True)
                    title_el = card.find(["h3", "h2", "h4"]) or link_el
                    title = title_el.get_text(strip=True) if title_el else ""
                    href = link_el.get("href", "") if link_el else ""
                    url = urljoin(base_url, href)
                    loc_el = card.find(class_=lambda c: c and "location" in str(c).lower())
                    location = loc_el.get_text(strip=True) if loc_el else "España"
                    external_id = href.split("/")[-1] or self._synthetic_id(title, slug)
                    if title:
                        jobs.append({
                            "site": self.SITE,
                            "external_id": f"{slug}_{external_id}",
                            "url": url or base_url,
                            "title": title,
                            "company": company_name,
                            "location": location,
                            "description": None,
                            "salary_raw": None,
                            "contract_type": None,
                            "cv_profile": self._assign_cv_profile(title, cv_profile),
                            "raw_data": {"title": title, "url": url},
                        })
                except Exception:
                    pass

        except ImportError:
            self._log.warning("personio.bs4_unavailable", tip="pip install beautifulsoup4")
        except Exception as exc:
            self._log.warning("personio.html_parse_error", slug=slug, error=str(exc))

        return jobs

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _synthetic_id(self, title: str, slug: str) -> str:
        raw = f"{self.SITE}|{slug}|{title.lower()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def _assign_cv_profile(self, title: str, default: str) -> str:
        t = title.lower()
        if any(kw in t for kw in ["frontend", "front-end", "react", "vue", "angular"]):
            return "frontend_dev"
        if any(kw in t for kw in ["fullstack", "full stack", "backend", "software", "developer", "engineer", "python", "java", "node"]):
            return "fullstack_dev"
        if any(kw in t for kw in ["logistics", "logística", "warehouse", "almacén", "driver", "reparto"]):
            return "logistics"
        return default
