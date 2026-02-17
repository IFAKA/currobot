"""JobToday Tier 1 scraper — httpx JSON API."""
from __future__ import annotations

import hashlib
from typing import Any, Optional

import httpx
import structlog

from backend.scrapers.base import BaseScraper

log = structlog.get_logger(__name__)


class JobTodayScraper(BaseScraper):
    """Scrape JobToday public API for retail and logistics jobs in Spain."""

    SITE = "jobtoday"
    API_BASE = "https://jobtoday.com/api/v3/jobs"

    HEADERS = {
        "Accept": "application/json",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    }

    CATEGORIES = ["retail", "logistics", "hospitality", "cleaning", "security"]
    PAGE_SIZE = 20

    def __init__(self, db_session_factory: Any) -> None:
        super().__init__(self.SITE, db_session_factory)

    # ------------------------------------------------------------------
    # Main scrape
    # ------------------------------------------------------------------

    async def scrape(self) -> list[dict]:
        all_jobs: list[dict] = []

        async with httpx.AsyncClient(
            headers=self.HEADERS,
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            for category in self.CATEGORIES:
                self._log.info("jobtoday.fetching_category", category=category)
                jobs = await self._fetch_category(client, category)
                all_jobs.extend(jobs)
                self._log.info("jobtoday.category_done", category=category, count=len(jobs))
                await self._rate_limit()

        # Deduplicate by external_id
        seen: set[str] = set()
        unique: list[dict] = []
        for job in all_jobs:
            eid = job.get("external_id", "")
            if eid not in seen:
                seen.add(eid)
                unique.append(job)

        self._log.info("jobtoday.total", total=len(unique))
        return unique

    # ------------------------------------------------------------------
    # Per-category fetch with pagination
    # ------------------------------------------------------------------

    async def _fetch_category(self, client: httpx.AsyncClient, category: str) -> list[dict]:
        jobs: list[dict] = []
        offset = 0
        max_pages = 10

        for _ in range(max_pages):
            params: dict[str, Any] = {
                "country": "ES",
                "category": category,
                "limit": self.PAGE_SIZE,
                "offset": offset,
                "sort": "date",
            }

            try:
                response = await client.get(self.API_BASE, params=params)
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPStatusError as exc:
                self._log.warning(
                    "jobtoday.http_error",
                    category=category,
                    status=exc.response.status_code,
                    error=str(exc),
                )
                break
            except Exception as exc:
                self._log.warning("jobtoday.fetch_error", category=category, error=str(exc))
                break

            page_jobs = self._extract_jobs(data)
            if not page_jobs:
                break

            jobs.extend(page_jobs)
            offset += self.PAGE_SIZE

            # If we got fewer than page size, no more pages
            if len(page_jobs) < self.PAGE_SIZE:
                break

            await self._rate_limit()

        return jobs

    # ------------------------------------------------------------------
    # Extraction + normalisation
    # ------------------------------------------------------------------

    def _extract_jobs(self, data: Any) -> list[dict]:
        raw_list: list[dict] = []

        if isinstance(data, dict):
            raw_list = (
                data.get("jobs")
                or data.get("results")
                or data.get("data")
                or data.get("items")
                or []
            )
        elif isinstance(data, list):
            raw_list = data

        result: list[dict] = []
        for raw in raw_list:
            job = self._normalise_job(raw)
            if job:
                result.append(job)
        return result

    def _normalise_job(self, raw: dict) -> Optional[dict]:
        external_id = (
            str(raw.get("id") or raw.get("jobId") or raw.get("_id") or "")
        )
        if not external_id:
            external_id = self._synthetic_id(raw)

        title = raw.get("title") or raw.get("jobTitle") or raw.get("position") or ""
        company = (
            raw.get("company")
            or raw.get("companyName")
            or raw.get("employer", {}).get("name", "")
            or "N/A"
        )
        if isinstance(company, dict):
            company = company.get("name") or company.get("label") or "N/A"

        location = (
            raw.get("location")
            or raw.get("city")
            or raw.get("address", {}).get("city", "")
            or "España"
        )
        if isinstance(location, dict):
            location = location.get("city") or location.get("label") or "España"

        description = raw.get("description") or raw.get("snippet") or ""
        salary_raw = raw.get("salary") or raw.get("salaryText") or None
        if isinstance(salary_raw, dict):
            salary_raw = salary_raw.get("text") or salary_raw.get("description")

        url = raw.get("url") or raw.get("link") or raw.get("jobUrl") or ""
        if not url and external_id:
            url = f"https://jobtoday.com/jobs/{external_id}"

        contract_type = raw.get("contractType") or raw.get("jobType") or None

        return {
            "site": self.SITE,
            "external_id": external_id,
            "url": url,
            "title": title,
            "company": company,
            "location": location,
            "description": description,
            "salary_raw": str(salary_raw) if salary_raw else None,
            "contract_type": contract_type,
            "cv_profile": self._assign_cv_profile(title),
            "raw_data": raw,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _synthetic_id(self, raw: dict) -> str:
        title = raw.get("title", "")
        company = raw.get("company", "") if isinstance(raw.get("company"), str) else ""
        location = raw.get("location", "") if isinstance(raw.get("location"), str) else ""
        raw_str = f"{self.SITE}|{title.lower()}|{company.lower()}|{location.lower()}"
        return hashlib.sha256(raw_str.encode()).hexdigest()[:32]

    def _assign_cv_profile(self, title: str) -> str:
        t = title.lower()
        if any(kw in t for kw in ["cajero", "cajera", "caja", "dependiente", "dependienta", "cashier"]):
            return "cashier"
        if any(kw in t for kw in ["reponedor", "almacén", "almacen", "stock", "mozo", "operario", "warehouse"]):
            return "stocker"
        if any(kw in t for kw in ["repartidor", "delivery", "conductor", "logística", "logistica", "mensajero"]):
            return "logistics"
        return "logistics"
