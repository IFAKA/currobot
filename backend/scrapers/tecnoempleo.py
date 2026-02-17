"""Tecnoempleo.com Tier 1 scraper — httpx + BeautifulSoup."""
from __future__ import annotations

import hashlib
import re
from typing import Any, Optional
from urllib.parse import urljoin, urlparse, urlencode

import httpx
import structlog

try:
    from bs4 import BeautifulSoup, Tag
    _BS4_AVAILABLE = True
except ImportError:
    _BS4_AVAILABLE = False

from backend.scrapers.base import BaseScraper

log = structlog.get_logger(__name__)


class TecnoempleoScraper(BaseScraper):
    """Scrape Tecnoempleo.com for React/Frontend/Fullstack developer positions in Spain."""

    SITE = "tecnoempleo"
    BASE_URL = "https://www.tecnoempleo.com"
    SEARCH_URL = "https://www.tecnoempleo.com/busqueda-empleo.php"

    HEADERS = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.tecnoempleo.com/",
    }

    SEARCH_QUERIES = [
        "react frontend",
        "fullstack developer",
        "typescript developer",
        "vue.js developer",
        "angular developer",
    ]

    def __init__(self, db_session_factory: Any) -> None:
        super().__init__(self.SITE, db_session_factory)
        if not _BS4_AVAILABLE:
            raise ImportError("beautifulsoup4 is required: pip install beautifulsoup4")

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
            for query in self.SEARCH_QUERIES:
                self._log.info("tecnoempleo.searching", query=query)
                jobs = await self._search_query(client, query)
                all_jobs.extend(jobs)
                self._log.info("tecnoempleo.query_done", query=query, count=len(jobs))
                await self._rate_limit()

        # Deduplicate by external_id
        seen: set[str] = set()
        unique: list[dict] = []
        for job in all_jobs:
            eid = job.get("external_id", "")
            if eid not in seen:
                seen.add(eid)
                unique.append(job)

        self._log.info("tecnoempleo.total", total=len(unique))
        return unique

    # ------------------------------------------------------------------
    # Per-query search with pagination
    # ------------------------------------------------------------------

    async def _search_query(self, client: httpx.AsyncClient, query: str) -> list[dict]:
        jobs: list[dict] = []
        max_pages = 5

        for page_num in range(1, max_pages + 1):
            url = self._build_search_url(query, page_num)
            try:
                response = await client.get(url)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                self._log.warning("tecnoempleo.http_error", url=url, error=str(exc))
                break

            page_jobs = self._parse_page(response.text, response.url)
            if not page_jobs:
                self._log.debug("tecnoempleo.no_more_jobs", query=query, page=page_num)
                break

            jobs.extend(page_jobs)

            if page_num < max_pages:
                await self._rate_limit()

        return jobs

    # ------------------------------------------------------------------
    # HTML parsing
    # ------------------------------------------------------------------

    def _parse_page(self, html: str, base_url: Any = None) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        jobs: list[dict] = []

        # Tecnoempleo job cards are typically <div class="offer-item"> or similar
        selectors = [
            ".oferta-empleo",
            ".offer-item",
            ".job-item",
            "article.oferta",
            "[class*='oferta']",
            "[class*='offer-item']",
            ".col-md-12.border.rounded",
        ]

        cards = []
        for selector in selectors:
            cards = soup.select(selector)
            if cards:
                self._log.debug("tecnoempleo.selector_matched", selector=selector, count=len(cards))
                break

        # Fallback: look for structured job links
        if not cards:
            # Try to find job listing links directly
            job_links = soup.find_all("a", href=re.compile(r"/oferta-empleo/|/empleo/"))
            for link in job_links:
                job = self._parse_link_as_job(link, base_url)
                if job:
                    jobs.append(job)
            return jobs

        for card in cards:
            job = self._parse_card(card, base_url)
            if job:
                jobs.append(job)

        return jobs

    def _parse_card(self, card: Any, base_url: Any = None) -> Optional[dict]:
        try:
            # Title and URL
            title_el = card.find(["h2", "h3", "h4"]) or card.find(class_=re.compile("title|puesto|nombre", re.I))
            link_el = (title_el.find("a", href=True) if title_el else None) or card.find("a", href=True)

            title = ""
            url = ""
            if link_el:
                title = link_el.get_text(strip=True)
                href = link_el.get("href", "")
                url = urljoin(str(base_url or self.BASE_URL), href)
            elif title_el:
                title = title_el.get_text(strip=True)

            if not title:
                return None

            # Company
            company_el = card.find(class_=re.compile("empresa|company|employer", re.I))
            company = company_el.get_text(strip=True) if company_el else "N/A"

            # Location
            location_el = card.find(class_=re.compile("location|lugar|provincia|ciudad", re.I))
            location = location_el.get_text(strip=True) if location_el else "España"

            # Salary
            salary_el = card.find(class_=re.compile("salario|salary|sueldo", re.I))
            salary_raw = salary_el.get_text(strip=True) if salary_el else None

            # External ID from URL
            external_id = self._extract_id_from_url(url) or self._synthetic_id(title, company)

            return {
                "site": self.SITE,
                "external_id": external_id,
                "url": url or self.BASE_URL,
                "title": title,
                "company": company,
                "location": location,
                "description": None,
                "salary_raw": salary_raw if salary_raw else None,
                "contract_type": None,
                "cv_profile": self._assign_cv_profile(title),
                "raw_data": {"title": title, "company": company, "location": location},
            }
        except Exception as exc:
            self._log.debug("tecnoempleo.card_parse_error", error=str(exc))
            return None

    def _parse_link_as_job(self, link: Any, base_url: Any = None) -> Optional[dict]:
        """Parse a simple anchor tag as a job entry."""
        try:
            title = link.get_text(strip=True)
            href = link.get("href", "")
            url = urljoin(str(base_url or self.BASE_URL), href)

            if not title or len(title) < 5:
                return None

            external_id = self._extract_id_from_url(url) or self._synthetic_id(title, "")

            return {
                "site": self.SITE,
                "external_id": external_id,
                "url": url,
                "title": title,
                "company": "N/A",
                "location": "España",
                "description": None,
                "salary_raw": None,
                "contract_type": None,
                "cv_profile": self._assign_cv_profile(title),
                "raw_data": {"title": title, "url": url},
            }
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_search_url(self, query: str, page: int = 1) -> str:
        params: dict[str, Any] = {
            "te": query,
            "tp": "1",   # Spain
        }
        if page > 1:
            params["pg"] = page
        return f"{self.SEARCH_URL}?{urlencode(params)}"

    def _extract_id_from_url(self, url: str) -> str:
        if not url:
            return ""
        path = urlparse(url).path
        parts = [p for p in path.split("/") if p]
        return parts[-1] if parts else ""

    def _synthetic_id(self, title: str, company: str) -> str:
        raw = f"{self.SITE}|{title.lower()}|{company.lower()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def _assign_cv_profile(self, title: str) -> str:
        t = title.lower()
        if any(kw in t for kw in ["frontend", "front-end", "react", "vue", "angular", "css", "html"]):
            return "frontend_dev"
        if any(kw in t for kw in ["fullstack", "full stack", "full-stack", "backend", "node", "python", "java", "developer", "desarrollador"]):
            return "fullstack_dev"
        return "fullstack_dev"
