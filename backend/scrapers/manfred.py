"""Manfred.com tech job board scraper."""
from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any, Optional
from urllib.parse import urljoin

import httpx
import structlog

from backend.scrapers.base import BaseScraper

log = structlog.get_logger(__name__)

SPAIN_KEYWORDS = ["spain", "españa", "madrid", "barcelona", "remote", "remoto", "híbrido", "hibrido"]


class ManfredScraper(BaseScraper):
    """Scrape Manfred.com for tech jobs (Frontend, Fullstack, React, TypeScript)."""

    SITE = "manfred"
    BASE_URL = "https://www.getmanfred.com"
    API_BASE = "https://www.getmanfred.com/api/offers"
    JOBS_PAGE = "https://www.getmanfred.com/ofertas-empleo"

    HEADERS = {
        "Accept": "application/json, text/html, */*",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.getmanfred.com/",
    }

    TECH_KEYWORDS = [
        "frontend", "front-end", "react", "vue", "angular", "typescript", "javascript",
        "fullstack", "full stack", "full-stack", "node", "python", "backend", "developer",
        "desarrollador", "programador", "software", "engineer",
    ]

    def __init__(self, db_session_factory: Any) -> None:
        super().__init__(self.SITE, db_session_factory)

    # ------------------------------------------------------------------
    # Main scrape
    # ------------------------------------------------------------------

    async def scrape(self) -> list[dict]:
        all_jobs: list[dict] = []

        # Try the public API first
        api_jobs = await self._fetch_via_api()
        if api_jobs:
            all_jobs.extend(api_jobs)
            self._log.info("manfred.api_success", count=len(api_jobs))
        else:
            # Fall back to browser/HTML scrape
            self._log.info("manfred.falling_back_to_html")
            html_jobs = await self._fetch_via_html()
            all_jobs.extend(html_jobs)

        # Filter for Spain/Remote + tech roles
        filtered = [j for j in all_jobs if self._is_relevant(j)]

        # Deduplicate
        seen: set[str] = set()
        unique: list[dict] = []
        for job in filtered:
            eid = job.get("external_id", "")
            if eid not in seen:
                seen.add(eid)
                unique.append(job)

        self._log.info("manfred.total", total=len(unique))
        return unique

    # ------------------------------------------------------------------
    # Strategy 1: JSON API
    # ------------------------------------------------------------------

    async def _fetch_via_api(self) -> list[dict]:
        jobs: list[dict] = []

        async with httpx.AsyncClient(headers=self.HEADERS, follow_redirects=True, timeout=30.0) as client:
            page = 1
            max_pages = 20
            page_size = 20

            while page <= max_pages:
                params: dict[str, Any] = {
                    "page": page,
                    "limit": page_size,
                    "status": "active",
                }
                try:
                    resp = await client.get(self.API_BASE, params=params)
                    if resp.status_code == 404:
                        self._log.debug("manfred.api_404")
                        return []
                    resp.raise_for_status()
                    data = resp.json()
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code in (404, 405, 422):
                        return []
                    self._log.warning("manfred.api_error", error=str(exc))
                    return jobs
                except Exception as exc:
                    self._log.warning("manfred.api_exception", error=str(exc))
                    return jobs

                page_jobs = self._parse_api_response(data)
                if not page_jobs:
                    break

                jobs.extend(page_jobs)
                page += 1

                if len(page_jobs) < page_size:
                    break

                await self._rate_limit()

        return jobs

    def _parse_api_response(self, data: Any) -> list[dict]:
        raw_list: list[dict] = []

        if isinstance(data, dict):
            raw_list = (
                data.get("offers")
                or data.get("jobs")
                or data.get("data")
                or data.get("results")
                or []
            )
        elif isinstance(data, list):
            raw_list = data

        result: list[dict] = []
        for raw in raw_list:
            if not isinstance(raw, dict):
                continue
            job = self._normalise_api_job(raw)
            if job:
                result.append(job)
        return result

    def _normalise_api_job(self, raw: dict) -> Optional[dict]:
        external_id = str(raw.get("id") or raw.get("slug") or raw.get("_id") or "")
        if not external_id:
            return None

        title = raw.get("position") or raw.get("title") or raw.get("jobTitle") or ""
        company_node = raw.get("company") or {}
        company = (
            company_node.get("name") if isinstance(company_node, dict) else company_node
        ) or raw.get("companyName") or "N/A"

        location = self._extract_location(raw)
        description = raw.get("description") or raw.get("summary") or ""
        salary_node = raw.get("salary") or raw.get("salaryRange") or {}
        salary_raw = None
        if isinstance(salary_node, dict):
            min_s = salary_node.get("min") or salary_node.get("from")
            max_s = salary_node.get("max") or salary_node.get("to")
            currency = salary_node.get("currency", "€")
            if min_s or max_s:
                salary_raw = f"{min_s or '?'} - {max_s or '?'} {currency}"
        elif salary_node:
            salary_raw = str(salary_node)

        slug = raw.get("slug") or external_id
        url = f"{self.BASE_URL}/oferta/{slug}" if slug else f"{self.BASE_URL}/ofertas-empleo"

        cv_profile = self._assign_cv_profile(title)

        return {
            "site": self.SITE,
            "external_id": external_id,
            "url": url,
            "title": title,
            "company": company,
            "location": location,
            "description": description,
            "salary_raw": salary_raw,
            "contract_type": raw.get("contractType") or raw.get("contract"),
            "cv_profile": cv_profile,
            "raw_data": raw,
        }

    def _extract_location(self, raw: dict) -> str:
        locations = raw.get("locations") or []
        if isinstance(locations, list) and locations:
            loc = locations[0]
            if isinstance(loc, dict):
                return loc.get("label") or loc.get("city") or loc.get("name") or "España"
            return str(loc)
        return (
            raw.get("location")
            or raw.get("city")
            or raw.get("locationLabel")
            or "España"
        )

    # ------------------------------------------------------------------
    # Strategy 2: HTML scrape with browser intercept
    # ------------------------------------------------------------------

    async def _fetch_via_html(self) -> list[dict]:
        """Fetch Manfred offers page and parse HTML/JSON from embedded data."""
        jobs: list[dict] = []

        async with httpx.AsyncClient(headers=self.HEADERS, follow_redirects=True, timeout=30.0) as client:
            try:
                resp = await client.get(self.JOBS_PAGE)
                resp.raise_for_status()
                html = resp.text

                # Try to find embedded JSON (Next.js __NEXT_DATA__ pattern)
                import re
                match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
                if match:
                    next_data = json.loads(match.group(1))
                    offers = self._dig_next_data(next_data)
                    for raw in offers:
                        job = self._normalise_api_job(raw)
                        if job:
                            jobs.append(job)
                else:
                    self._log.debug("manfred.no_next_data_found")

            except Exception as exc:
                self._log.warning("manfred.html_fetch_error", error=str(exc))

        return jobs

    def _dig_next_data(self, data: Any, depth: int = 0) -> list[dict]:
        """Recursively search Next.js page props for offer lists."""
        if depth > 8 or not isinstance(data, (dict, list)):
            return []

        if isinstance(data, list):
            if all(isinstance(x, dict) and ("position" in x or "title" in x or "id" in x) for x in data[:3]) and data:
                return data
            result = []
            for item in data:
                result.extend(self._dig_next_data(item, depth + 1))
            return result

        if isinstance(data, dict):
            for key in ("offers", "jobs", "positions", "listings"):
                if key in data and isinstance(data[key], list):
                    return data[key]
            result = []
            for v in data.values():
                result.extend(self._dig_next_data(v, depth + 1))
            return result

        return []

    # ------------------------------------------------------------------
    # Filters and helpers
    # ------------------------------------------------------------------

    def _is_relevant(self, job: dict) -> bool:
        """Accept only tech roles with Spain/Remote location."""
        title = (job.get("title") or "").lower()
        location = (job.get("location") or "").lower()

        tech_match = any(kw in title for kw in self.TECH_KEYWORDS)
        spain_match = any(kw in location for kw in SPAIN_KEYWORDS)

        return tech_match and spain_match

    def _assign_cv_profile(self, title: str) -> str:
        t = title.lower()
        if any(kw in t for kw in ["frontend", "front-end", "react", "vue", "angular", "css", "html"]):
            return "frontend_dev"
        return "fullstack_dev"
