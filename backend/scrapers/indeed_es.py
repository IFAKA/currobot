"""Indeed.es Tier 2 scraper — intercepts internal vsearch/rpc API calls."""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Optional
from urllib.parse import quote_plus

import structlog

from backend.scrapers.base import BaseScraper
from backend.scrapers.browser_pool import browser_pool

log = structlog.get_logger(__name__)


class IndeedESScraper(BaseScraper):
    """Scrape Indeed.es by intercepting the internal job-search API traffic."""

    SITE = "indeed_es"

    SEARCH_QUERIES: list[str] = [
        "cajero",
        "reponedor",
        "mozo almacen",
        "dependiente",
        "frontend developer",
        "fullstack developer",
        "react developer",
    ]
    LOCATION = "España"
    BASE_URL = "https://es.indeed.com"

    def __init__(self, db_session_factory: Any) -> None:
        super().__init__(self.SITE, db_session_factory)

    # ------------------------------------------------------------------
    # Main scrape
    # ------------------------------------------------------------------

    async def scrape(self) -> list[dict]:
        context = await browser_pool.get_context(self.SITE)
        page = await context.new_page()
        all_jobs: list[dict] = []

        try:
            for query in self.SEARCH_QUERIES:
                self._log.info("indeed_es.searching", query=query)
                jobs = await self._search_query(page, query)
                all_jobs.extend(jobs)
                self._log.info("indeed_es.query_done", query=query, count=len(jobs))
                await self._rate_limit()

            await browser_pool.save_cookies(self.SITE, context)

        except Exception as exc:
            self._log.exception("indeed_es.scrape_error", error=str(exc))
        finally:
            try:
                await page.close()
            except Exception:
                pass
            await browser_pool.close_context(self.SITE)

        self._log.info("indeed_es.total", total=len(all_jobs))
        return all_jobs

    # ------------------------------------------------------------------
    # Per-query logic
    # ------------------------------------------------------------------

    async def _search_query(self, page: Any, query: str) -> list[dict]:
        """Navigate to Indeed search page and intercept API responses."""
        captured_jobs: list[dict] = []
        cursor: Optional[str] = None
        page_num = 0
        max_pages = 5

        async def handle_route(route: Any, request: Any) -> None:
            try:
                response = await route.fetch()
                body = await response.body()
                try:
                    data = json.loads(body)
                    self._extract_jobs_from_response(data, captured_jobs)
                except (json.JSONDecodeError, ValueError):
                    pass
                await route.fulfill(response=response)
            except Exception as exc:
                self._log.debug("indeed_es.route_error", error=str(exc))
                try:
                    await route.continue_()
                except Exception:
                    pass

        await page.route("**/api/vsearch/l**", handle_route)
        await page.route("**/rpc/jobsearch**", handle_route)
        await page.route("**/jobs/search**", handle_route)

        while page_num < max_pages:
            url = self._build_search_url(query, self.LOCATION, start=page_num * 10)
            try:
                await page.goto(url, wait_until="networkidle", timeout=30_000)
                await asyncio.sleep(2)
            except Exception as exc:
                self._log.warning("indeed_es.navigation_error", url=url, error=str(exc))
                break

            # If no new jobs captured this page, stop paginating
            before = len(captured_jobs)
            await asyncio.sleep(1)
            after = len(captured_jobs)

            if after == before and page_num > 0:
                self._log.debug("indeed_es.no_new_jobs_on_page", page=page_num)
                break

            page_num += 1
            await self._rate_limit()

        await page.unroute("**/api/vsearch/l**")
        await page.unroute("**/rpc/jobsearch**")
        await page.unroute("**/jobs/search**")

        # Normalise and enrich
        result: list[dict] = []
        seen: set[str] = set()
        for raw in captured_jobs:
            job = self._normalise_job(raw)
            if job and job["external_id"] not in seen:
                seen.add(job["external_id"])
                result.append(job)

        return result

    # ------------------------------------------------------------------
    # Response extraction
    # ------------------------------------------------------------------

    def _extract_jobs_from_response(self, data: Any, out: list[dict]) -> None:
        """Try multiple known Indeed API response shapes."""
        # Shape 1: {"jobResults": [{"job": {...}}]}
        if isinstance(data, dict):
            for item in data.get("jobResults", []):
                job_node = item.get("job") or item
                if isinstance(job_node, dict):
                    out.append(job_node)

            # Shape 2: {"results": [...]}
            for item in data.get("results", []):
                if isinstance(item, dict):
                    out.append(item)

            # Shape 3: {"metaData": {"jobResultsPayload": {"results": [...]}}}
            meta = data.get("metaData", {})
            payload = meta.get("jobResultsPayload", {})
            for item in payload.get("results", []):
                if isinstance(item, dict):
                    out.append(item)

        elif isinstance(data, list):
            out.extend(item for item in data if isinstance(item, dict))

    # ------------------------------------------------------------------
    # Normalisation
    # ------------------------------------------------------------------

    def _normalise_job(self, raw: dict) -> Optional[dict]:
        """Convert a raw Indeed API job dict to our standard schema."""
        external_id = (
            raw.get("jobkey")
            or raw.get("id")
            or raw.get("jobId")
            or raw.get("entityKey")
        )
        if not external_id:
            return None

        title = (
            raw.get("title")
            or raw.get("displayTitle")
            or raw.get("normalizedTitle")
            or ""
        )
        company = (
            raw.get("company")
            or raw.get("companyName")
            or raw.get("employer", {}).get("name", "")
            or ""
        )
        location_raw = (
            raw.get("formattedLocation")
            or raw.get("location")
            or raw.get("city")
            or ""
        )
        description = (
            raw.get("snippet")
            or raw.get("description")
            or raw.get("descriptionSnippets", [""])[0]
            or ""
        )
        salary_raw = (
            raw.get("salarySnippet", {}).get("text")
            or raw.get("estimatedSalary", {}).get("text")
            or raw.get("formattedSalary")
            or None
        )
        job_url = (
            raw.get("viewJobLink")
            or raw.get("link")
            or f"{self.BASE_URL}/viewjob?jk={external_id}"
        )
        if job_url and not job_url.startswith("http"):
            job_url = self.BASE_URL + job_url

        cv_profile = self._assign_cv_profile(title)

        return {
            "site": self.SITE,
            "external_id": str(external_id),
            "url": job_url,
            "title": title,
            "company": company,
            "location": location_raw,
            "description": description,
            "salary_raw": salary_raw,
            "contract_type": raw.get("contractType") or raw.get("jobType"),
            "cv_profile": cv_profile,
            "raw_data": raw,
        }

    # ------------------------------------------------------------------
    # URL builder
    # ------------------------------------------------------------------

    def _build_search_url(self, query: str, location: str, start: int = 0) -> str:
        q = quote_plus(query)
        loc = quote_plus(location)
        return f"{self.BASE_URL}/jobs?q={q}&l={loc}&start={start}&sort=date"

    # ------------------------------------------------------------------
    # CV profile assignment
    # ------------------------------------------------------------------

    def _assign_cv_profile(self, title: str) -> str:
        t = title.lower()

        # Tech roles
        if any(kw in t for kw in ["react", "frontend", "front-end", "front end", "javascript", "typescript", "vue", "angular"]):
            return "frontend_dev"
        if any(kw in t for kw in ["fullstack", "full stack", "full-stack", "node", "backend", "python", "java", "golang"]):
            return "fullstack_dev"

        # Retail cashier
        if any(kw in t for kw in ["cajero", "cajera", "dependiente", "dependienta", "caja", "atención al cliente"]):
            return "cashier"

        # Stocker / warehouse
        if any(kw in t for kw in ["reponedor", "reponedora", "almacén", "almacen", "stock", "operario", "mozo"]):
            return "stocker"

        # Default
        return "logistics"
