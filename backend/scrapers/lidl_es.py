"""Lidl España Tier 1 scraper — httpx + BeautifulSoup."""
from __future__ import annotations

import hashlib
import re
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import httpx
import structlog

try:
    from bs4 import BeautifulSoup
    _BS4_AVAILABLE = True
except ImportError:
    _BS4_AVAILABLE = False

from backend.scrapers.base import BaseScraper

log = structlog.get_logger(__name__)

RELEVANT_KEYWORDS = [
    "tienda", "almacén", "almacen", "logística", "logistica",
    "cajero", "cajera", "reponedor", "reponedora", "operario",
    "operaria", "dependiente", "dependienta", "comercial",
]


class LidlESScraper(BaseScraper):
    """Scrape Lidl España career portal."""

    SITE = "lidl_es"
    BASE_URL = "https://jobs.lidl.es"
    VACANCIES_URL = "https://jobs.lidl.es/vacancies"

    HEADERS = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    }

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
            page_num = 1
            max_pages = 10

            while page_num <= max_pages:
                url = self._build_url(page_num)
                self._log.info("lidl_es.fetching_page", url=url)

                try:
                    response = await client.get(url)
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    self._log.warning("lidl_es.http_error", url=url, error=str(exc))
                    break

                jobs_on_page = self._parse_page(response.text)

                if not jobs_on_page:
                    self._log.info("lidl_es.no_more_jobs", page=page_num)
                    break

                all_jobs.extend(jobs_on_page)
                self._log.info("lidl_es.page_done", page=page_num, found=len(jobs_on_page))
                page_num += 1
                await self._rate_limit()

        # Deduplicate
        seen: set[str] = set()
        unique: list[dict] = []
        for job in all_jobs:
            eid = job.get("external_id", "")
            if eid not in seen:
                seen.add(eid)
                unique.append(job)

        self._log.info("lidl_es.total", total=len(unique))
        return unique

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse_page(self, html: str) -> list[dict]:
        """Parse job listing cards from HTML."""
        soup = BeautifulSoup(html, "html.parser")
        jobs: list[dict] = []

        # Lidl typically uses a list of job cards
        selectors = [
            "article.job-item",
            ".vacancy-item",
            ".job-listing__item",
            "[class*='job-item']",
            "[class*='vacancy']",
            "li[class*='job']",
        ]

        cards = []
        for selector in selectors:
            cards = soup.select(selector)
            if cards:
                break

        # Fallback: look for any link that looks like a job posting
        if not cards:
            cards = soup.find_all("a", href=re.compile(r"/vacancies/|/job/|/jobs/"))

        for card in cards:
            job = self._parse_card(card)
            if job and self._is_relevant(job.get("title", "")):
                jobs.append(job)

        return jobs

    def _parse_card(self, card: Any) -> Optional[dict]:
        """Extract job data from a single card element."""
        try:
            # Try to get the link
            link_el = card if card.name == "a" else card.find("a", href=True)
            href = ""
            if link_el and link_el.has_attr("href"):
                href = link_el["href"]
                if not href.startswith("http"):
                    href = urljoin(self.BASE_URL, href)

            # Title
            title_el = card.find(["h2", "h3", "h4", "[class*='title']"])
            if not title_el:
                title_el = card.find(class_=re.compile("title|position|job-name", re.I))
            title = title_el.get_text(strip=True) if title_el else card.get_text(strip=True)[:100]

            # Location
            location_el = card.find(class_=re.compile("location|place|city", re.I))
            location = location_el.get_text(strip=True) if location_el else "España"

            # Contract type
            contract_el = card.find(class_=re.compile("contract|type|jornada", re.I))
            contract_type = contract_el.get_text(strip=True) if contract_el else None

            # External ID from URL slug
            external_id = self._extract_id_from_url(href) or self._synthetic_id(title, location)

            if not title:
                return None

            return {
                "site": self.SITE,
                "external_id": external_id,
                "url": href or self.BASE_URL,
                "title": title,
                "company": "Lidl España",
                "location": location,
                "description": None,
                "salary_raw": None,
                "contract_type": contract_type,
                "cv_profile": self._assign_cv_profile(title),
                "raw_data": {"href": href, "title": title},
            }
        except Exception as exc:
            self._log.debug("lidl_es.card_parse_error", error=str(exc))
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_url(self, page: int) -> str:
        if page == 1:
            return f"{self.VACANCIES_URL}?country=ES"
        return f"{self.VACANCIES_URL}?country=ES&page={page}"

    def _is_relevant(self, title: str) -> bool:
        t = title.lower()
        return any(kw in t for kw in RELEVANT_KEYWORDS)

    def _extract_id_from_url(self, url: str) -> str:
        if not url:
            return ""
        path = urlparse(url).path
        # Last non-empty path segment as ID
        parts = [p for p in path.split("/") if p]
        return parts[-1] if parts else ""

    def _synthetic_id(self, title: str, location: str) -> str:
        raw = f"{self.SITE}|{title.lower()}|{location.lower()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def _assign_cv_profile(self, title: str) -> str:
        t = title.lower()
        if any(kw in t for kw in ["cajero", "cajera", "caja", "dependiente", "dependienta"]):
            return "cashier"
        if any(kw in t for kw in ["reponedor", "reponedora", "almacén", "almacen", "stock", "operario", "mozo"]):
            return "stocker"
        if any(kw in t for kw in ["logística", "logistica", "transporte", "reparto"]):
            return "logistics"
        return "stocker"
