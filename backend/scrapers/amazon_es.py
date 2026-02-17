"""Amazon España Tier 3 scraper — stealth browser + API intercept."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Optional
from urllib.parse import urljoin

import structlog

from backend.scrapers.base import BaseScraper
from backend.scrapers.browser_pool import browser_pool

log = structlog.get_logger(__name__)

SEARCH_URLS = [
    "https://amazon.jobs/en/search?country%5B%5D=ESP&category%5B%5D=software-development",
    "https://amazon.jobs/en/search?country%5B%5D=ESP&category%5B%5D=operations-it-support-and-engineering",
    "https://amazon.jobs/en/search?country%5B%5D=ESP&category%5B%5D=fulfillment-operations",
]


class AmazonESScraper(BaseScraper):
    """Scrape Amazon.jobs for Spain positions using stealth browser + API intercept."""

    SITE = "amazon_es"
    BASE_URL = "https://amazon.jobs"
    API_BASE = "https://amazon.jobs/en/search.json"

    def __init__(self, db_session_factory: Any) -> None:
        super().__init__(self.SITE, db_session_factory)

    # ------------------------------------------------------------------
    # Main scrape
    # ------------------------------------------------------------------

    async def scrape(self) -> list[dict]:
        all_jobs: list[dict] = []

        # Try API-first approach (faster and more reliable when it works)
        api_jobs = await self._fetch_via_api()
        if api_jobs:
            all_jobs.extend(api_jobs)
            self._log.info("amazon_es.api_success", count=len(api_jobs))
        else:
            # Fall back to browser intercept
            self._log.info("amazon_es.falling_back_to_browser")
            browser_jobs = await self._fetch_via_browser()
            all_jobs.extend(browser_jobs)

        # Deduplicate
        seen: set[str] = set()
        unique: list[dict] = []
        for job in all_jobs:
            eid = job.get("external_id", "")
            if eid not in seen:
                seen.add(eid)
                unique.append(job)

        self._log.info("amazon_es.total", total=len(unique))
        return unique

    # ------------------------------------------------------------------
    # Strategy 1: Direct JSON API
    # ------------------------------------------------------------------

    async def _fetch_via_api(self) -> list[dict]:
        """Call Amazon Jobs JSON search API directly."""
        import httpx

        jobs: list[dict] = []
        categories = [
            "software-development",
            "operations-it-support-and-engineering",
            "fulfillment-operations",
        ]
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
            "Referer": "https://amazon.jobs/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "X-Requested-With": "XMLHttpRequest",
        }

        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=30.0) as client:
            for category in categories:
                offset = 0
                page_size = 10

                while True:
                    params: dict[str, Any] = {
                        "country[]": "ESP",
                        "category[]": category,
                        "offset": offset,
                        "result_limit": page_size,
                        "sort": "relevant",
                    }
                    try:
                        resp = await client.get(self.API_BASE, params=params)
                        if resp.status_code != 200:
                            self._log.debug("amazon_es.api_not_200", status=resp.status_code)
                            return []
                        data = resp.json()
                    except Exception as exc:
                        self._log.debug("amazon_es.api_exception", error=str(exc))
                        return []

                    page_jobs = self._parse_api_response(data)
                    if not page_jobs:
                        break

                    jobs.extend(page_jobs)
                    offset += page_size

                    total = data.get("count") or data.get("hits") or 0
                    if offset >= total or len(page_jobs) < page_size:
                        break

                    await self._rate_limit()

                await self._rate_limit()

        return jobs

    def _parse_api_response(self, data: Any) -> list[dict]:
        raw_list: list[dict] = []

        if isinstance(data, dict):
            raw_list = data.get("jobs") or data.get("results") or []
        elif isinstance(data, list):
            raw_list = data

        result: list[dict] = []
        for raw in raw_list:
            job = self._normalise_job(raw)
            if job:
                result.append(job)
        return result

    # ------------------------------------------------------------------
    # Strategy 2: Stealth browser with route intercept
    # ------------------------------------------------------------------

    async def _fetch_via_browser(self) -> list[dict]:
        context = await browser_pool.get_context(self.SITE)
        page = await context.new_page()
        captured_jobs: list[dict] = []

        async def handle_route(route: Any, request: Any) -> None:
            try:
                response = await route.fetch()
                body = await response.body()
                try:
                    data = json.loads(body)
                    page_jobs = self._parse_api_response(data)
                    captured_jobs.extend(page_jobs)
                except (json.JSONDecodeError, ValueError):
                    pass
                await route.fulfill(response=response)
            except Exception as exc:
                self._log.debug("amazon_es.route_error", error=str(exc))
                try:
                    await route.continue_()
                except Exception:
                    pass

        try:
            await page.route("**/api/jobs**", handle_route)
            await page.route("**/search.json**", handle_route)
            await page.route("**/jobs/search**", handle_route)

            for url in SEARCH_URLS:
                self._log.info("amazon_es.navigating", url=url)
                try:
                    await page.goto(url, wait_until="networkidle", timeout=60_000)
                    # Amazon is a heavy React SPA — wait extra
                    await asyncio.sleep(3)
                    await page.wait_for_load_state("networkidle", timeout=30_000)
                except Exception as exc:
                    self._log.warning("amazon_es.navigation_error", url=url, error=str(exc))
                    continue

                # Try to load more jobs by scrolling
                try:
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(2)
                except Exception:
                    pass

                await self._rate_limit()

            await browser_pool.save_cookies(self.SITE, context)

        except Exception as exc:
            self._log.exception("amazon_es.browser_error", error=str(exc))
        finally:
            try:
                await page.close()
            except Exception:
                pass
            await browser_pool.close_context(self.SITE)

        return captured_jobs

    # ------------------------------------------------------------------
    # Normalisation
    # ------------------------------------------------------------------

    def _normalise_job(self, raw: dict) -> Optional[dict]:
        external_id = str(
            raw.get("id_icims")
            or raw.get("id")
            or raw.get("jobId")
            or raw.get("requisitionId")
            or ""
        )
        if not external_id:
            return None

        title = raw.get("title") or raw.get("job_title") or ""
        company = "Amazon"

        location_raw = raw.get("location") or raw.get("normalized_location") or raw.get("city") or ""
        if isinstance(location_raw, list):
            location_raw = ", ".join(str(x) for x in location_raw)
        elif isinstance(location_raw, dict):
            location_raw = location_raw.get("label") or location_raw.get("name") or "España"

        description = (
            raw.get("description")
            or raw.get("job_description")
            or raw.get("summary")
            or ""
        )

        url_path = raw.get("job_path") or raw.get("url") or ""
        url = (
            (self.BASE_URL + url_path)
            if url_path and not url_path.startswith("http")
            else url_path or f"{self.BASE_URL}/en/jobs/{external_id}"
        )

        cv_profile = self._assign_cv_profile(title)

        return {
            "site": self.SITE,
            "external_id": external_id,
            "url": url,
            "title": title,
            "company": company,
            "location": location_raw,
            "description": description,
            "salary_raw": None,
            "contract_type": raw.get("employment_type") or raw.get("job_category"),
            "cv_profile": cv_profile,
            "raw_data": raw,
        }

    # ------------------------------------------------------------------
    # CV profile assignment
    # ------------------------------------------------------------------

    def _assign_cv_profile(self, title: str) -> str:
        t = title.lower()
        if any(kw in t for kw in ["software", "engineer", "developer", "frontend", "fullstack", "sde", "swe", "react", "python", "java"]):
            return "fullstack_dev"
        if any(kw in t for kw in ["warehouse", "fulfillment", "almacén", "almacen", "logistics", "logística", "operations", "operaciones"]):
            return "logistics"
        return "logistics"
