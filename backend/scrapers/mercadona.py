"""Mercadona Workday ATS scraper."""
from __future__ import annotations

import hashlib
from typing import Any, Optional

import httpx
import structlog

from backend.scrapers.base import BaseScraper

log = structlog.get_logger(__name__)

RELEVANT_KEYWORDS = [
    "cajero", "cajera", "reponedor", "reponedora", "almacén", "almacen",
    "tienda", "logística", "logistica", "operario", "operaria",
    "mozo", "dependiente", "dependienta",
]


class MercadonaScraper(BaseScraper):
    """Scrape Mercadona's Workday ATS for store/logistics positions."""

    SITE = "mercadona"
    WORKDAY_BASE = "https://mercadona.wd3.myworkdayjobs.com"
    COMPANY = "Mercadona"

    HEADERS = {
        "Accept": "application/json, text/html, */*",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Content-Type": "application/json",
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
        all_jobs: list[dict] = []

        async with httpx.AsyncClient(
            headers=self.HEADERS,
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            # Strategy 1: Try Workday public job search API (no auth required)
            jobs = await self._fetch_via_api(client)
            if jobs:
                all_jobs.extend(jobs)
                self._log.info("mercadona.api_success", count=len(jobs))
            else:
                # Strategy 2: Try RSS/XML feed
                self._log.info("mercadona.trying_xml_feed")
                jobs = await self._fetch_via_xml(client)
                all_jobs.extend(jobs)

        # Deduplicate
        seen: set[str] = set()
        unique: list[dict] = []
        for job in all_jobs:
            eid = job.get("external_id", "")
            if eid not in seen:
                seen.add(eid)
                unique.append(job)

        self._log.info("mercadona.total", total=len(unique))
        return unique

    # ------------------------------------------------------------------
    # Strategy 1: Workday internal job search API
    # ------------------------------------------------------------------

    async def _fetch_via_api(self, client: httpx.AsyncClient) -> list[dict]:
        """Attempt unauthenticated access to Workday job search service."""
        jobs: list[dict] = []
        offset = 0
        limit = 20

        while True:
            url = (
                f"{self.WORKDAY_BASE}/wday/authgwy/mercadona/"
                f"job-search-service/jobs?offset={offset}&limit={limit}"
            )
            try:
                response = await client.get(url, timeout=20.0)
                if response.status_code == 401:
                    self._log.debug("mercadona.api_requires_auth")
                    return []
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (401, 403):
                    return []
                self._log.warning("mercadona.api_error", error=str(exc))
                return jobs
            except Exception as exc:
                self._log.warning("mercadona.api_exception", error=str(exc))
                return jobs

            page_jobs = self._parse_api_response(data)
            if not page_jobs:
                break

            jobs.extend(page_jobs)
            offset += limit

            if len(page_jobs) < limit:
                break

            await self._rate_limit()

        return jobs

    # ------------------------------------------------------------------
    # Strategy 2: Workday public XML/HTML feed
    # ------------------------------------------------------------------

    async def _fetch_via_xml(self, client: httpx.AsyncClient) -> list[dict]:
        """Fall back to scraping the public Workday jobs page."""
        jobs: list[dict] = []
        page = 0
        limit = 20

        while True:
            url = (
                f"{self.WORKDAY_BASE}/en-US/Mercadona/jobs"
                f"?offset={page * limit}&limit={limit}"
            )
            try:
                # Try JSON endpoint first
                json_url = (
                    f"{self.WORKDAY_BASE}/wday/authgwy/mercadona/job-search-service/jobs"
                    f"?offset={page * limit}&limit={limit}"
                )
                resp = await client.get(json_url, timeout=20.0)
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        page_jobs = self._parse_api_response(data)
                        if not page_jobs:
                            break
                        jobs.extend(page_jobs)
                        if len(page_jobs) < limit:
                            break
                        page += 1
                        await self._rate_limit()
                        continue
                    except Exception:
                        pass

                # HTML fallback
                resp = await client.get(url, timeout=20.0)
                resp.raise_for_status()
                html_jobs = self._parse_html_response(resp.text)
                if not html_jobs:
                    break
                jobs.extend(html_jobs)
                if len(html_jobs) < limit:
                    break
                page += 1
                await self._rate_limit()

            except Exception as exc:
                self._log.warning("mercadona.xml_error", error=str(exc))
                break

        return jobs

    # ------------------------------------------------------------------
    # Response parsers
    # ------------------------------------------------------------------

    def _parse_api_response(self, data: Any) -> list[dict]:
        raw_list: list[dict] = []

        if isinstance(data, dict):
            raw_list = (
                data.get("jobPostings")
                or data.get("jobs")
                or data.get("results")
                or data.get("data")
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
        external_id = str(
            raw.get("bulletinId")
            or raw.get("id")
            or raw.get("externalId")
            or raw.get("jobPostingId")
            or ""
        )
        if not external_id:
            title_raw = raw.get("title") or raw.get("jobTitle") or ""
            loc_raw = raw.get("locationsText") or raw.get("location") or ""
            external_id = self._synthetic_id(title_raw, str(loc_raw))

        title = raw.get("title") or raw.get("jobTitle") or ""
        location = (
            raw.get("locationsText")
            or raw.get("location")
            or raw.get("primaryLocation")
            or "España"
        )
        if isinstance(location, dict):
            location = location.get("descriptor") or location.get("name") or "España"

        description = raw.get("jobDescription") or raw.get("description") or ""
        posted_at = raw.get("postedOn") or raw.get("publishedOn") or None

        url_path = raw.get("externalPath") or raw.get("url") or ""
        url = (
            f"{self.WORKDAY_BASE}{url_path}"
            if url_path and not url_path.startswith("http")
            else url_path or f"{self.WORKDAY_BASE}/en-US/Mercadona/job/{external_id}"
        )

        cv_profile = self._assign_cv_profile(title)

        return {
            "site": self.SITE,
            "external_id": external_id,
            "url": url,
            "title": title,
            "company": self.COMPANY,
            "location": location,
            "description": description,
            "salary_raw": None,
            "contract_type": raw.get("jobSchedule", {}).get("descriptor") if isinstance(raw.get("jobSchedule"), dict) else None,
            "cv_profile": cv_profile,
            "raw_data": raw,
        }

    def _parse_html_response(self, html: str) -> list[dict]:
        """Very basic HTML parser fallback using string search."""
        jobs: list[dict] = []
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            for card in soup.select("[data-automation-id='jobPostingsList'] li, .job-posting-item, li[class*='job']"):
                try:
                    title_el = card.find(["h3", "h2", "a"])
                    title = title_el.get_text(strip=True) if title_el else ""
                    link_el = card.find("a", href=True)
                    href = link_el["href"] if link_el else ""
                    if not href.startswith("http"):
                        href = self.WORKDAY_BASE + href
                    loc_el = card.find(class_=lambda c: c and "location" in c.lower())
                    location = loc_el.get_text(strip=True) if loc_el else "España"
                    external_id = self._synthetic_id(title, location)
                    if title:
                        jobs.append({
                            "site": self.SITE,
                            "external_id": external_id,
                            "url": href,
                            "title": title,
                            "company": self.COMPANY,
                            "location": location,
                            "description": None,
                            "salary_raw": None,
                            "contract_type": None,
                            "cv_profile": self._assign_cv_profile(title),
                            "raw_data": {"title": title, "location": location},
                        })
                except Exception:
                    pass
        except ImportError:
            self._log.warning("mercadona.bs4_unavailable", tip="pip install beautifulsoup4")
        except Exception as exc:
            self._log.warning("mercadona.html_parse_error", error=str(exc))
        return jobs

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _synthetic_id(self, title: str, location: str) -> str:
        raw = f"{self.SITE}|{title.lower()}|{location.lower()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def _assign_cv_profile(self, title: str) -> str:
        t = title.lower()
        if any(kw in t for kw in ["cajero", "cajera", "caja", "dependiente", "atención al cliente"]):
            return "cashier"
        if any(kw in t for kw in ["reponedor", "reponedora", "almacén", "almacen", "stock", "operario", "mozo"]):
            return "stocker"
        if any(kw in t for kw in ["logística", "logistica", "transporte", "reparto", "distribución"]):
            return "logistics"
        return "stocker"
