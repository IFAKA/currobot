"""Teamtailor ATS platform scraper — public jobs.json endpoint or HTML fallback."""
from __future__ import annotations

import hashlib
from typing import Any, Optional
from urllib.parse import urljoin

import httpx
import structlog

from backend.scrapers.base import BaseScraper

log = structlog.get_logger(__name__)

SPAIN_KEYWORDS = [
    "spain", "españa", "madrid", "barcelona", "remote", "remoto",
    "híbrido", "hibrido", "valencia", "sevilla", "bilbao",
]

# subdomain → cv_profile mapping for companies using Teamtailor
DEFAULT_COMPANIES: dict[str, str] = {
    "decathlon-spain": "logistics",
    "factorial": "fullstack_dev",
    "paack": "fullstack_dev",
    "stuart": "logistics",
    "amenitiz": "fullstack_dev",
    "holded": "fullstack_dev",
    "woffu": "fullstack_dev",
    "signaturit": "fullstack_dev",
    "deporvillage": "logistics",
}


class TeamtailorScraper(BaseScraper):
    """Scrape Teamtailor ATS public job pages for Spanish companies."""

    SITE = "teamtailor"

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
                    if source.scraper_type == "teamtailor":
                        extra = source.extra_config or {}
                        subdomain = extra.get("subdomain") or source.company_name.lower().replace(" ", "-")
                        companies[subdomain] = source.cv_profile
        except Exception as exc:
            self._log.warning("teamtailor.db_sources_error", error=str(exc))

        all_jobs: list[dict] = []

        async with httpx.AsyncClient(
            headers=self.HEADERS,
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            for subdomain, cv_profile in companies.items():
                self._log.info("teamtailor.fetching", subdomain=subdomain)
                jobs = await self._fetch_company(client, subdomain, cv_profile)
                all_jobs.extend(jobs)
                self._log.info("teamtailor.company_done", subdomain=subdomain, found=len(jobs))
                await self._rate_limit()

        # Deduplicate
        seen: set[str] = set()
        unique: list[dict] = []
        for job in all_jobs:
            eid = job.get("external_id", "")
            if eid not in seen:
                seen.add(eid)
                unique.append(job)

        self._log.info("teamtailor.total", total=len(unique))
        return unique

    # ------------------------------------------------------------------
    # Per-company fetch
    # ------------------------------------------------------------------

    async def _fetch_company(
        self, client: httpx.AsyncClient, subdomain: str, cv_profile: str
    ) -> list[dict]:
        base = f"https://{subdomain}.teamtailor.com"
        jobs_json_url = f"{base}/jobs.json"

        # Strategy 1: jobs.json endpoint
        try:
            resp = await client.get(jobs_json_url, timeout=20.0)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    jobs = self._parse_json_response(data, subdomain, cv_profile, base)
                    if jobs:
                        return jobs
                except Exception as exc:
                    self._log.debug("teamtailor.json_parse_error", subdomain=subdomain, error=str(exc))
        except Exception as exc:
            self._log.debug("teamtailor.json_fetch_error", subdomain=subdomain, error=str(exc))

        # Strategy 2: HTML scrape of /jobs page
        return await self._fetch_html(client, subdomain, cv_profile, base)

    # ------------------------------------------------------------------
    # JSON response parser
    # ------------------------------------------------------------------

    def _parse_json_response(
        self, data: Any, subdomain: str, cv_profile: str, base_url: str
    ) -> list[dict]:
        raw_list: list[dict] = []

        if isinstance(data, dict):
            raw_list = (
                data.get("jobs")
                or data.get("data")
                or data.get("positions")
                or []
            )
            # JSONAPI format: {"data": [{"type": "jobs", "id": ..., "attributes": {...}}]}
            if not raw_list and "data" in data:
                raw_list = data["data"] if isinstance(data["data"], list) else []
        elif isinstance(data, list):
            raw_list = data

        result: list[dict] = []
        for raw in raw_list:
            if not isinstance(raw, dict):
                continue

            # Handle JSONAPI format
            if raw.get("type") == "jobs" and "attributes" in raw:
                attrs = raw["attributes"]
                attrs["id"] = raw.get("id")
                raw = attrs

            location_raw = (
                raw.get("location")
                or raw.get("city")
                or raw.get("remote_status")
                or ""
            )
            if isinstance(location_raw, dict):
                location_raw = location_raw.get("name") or location_raw.get("city") or ""

            if location_raw and not self._is_spain_or_remote(str(location_raw)):
                continue

            job = self._normalise_json_job(raw, subdomain, cv_profile, base_url, str(location_raw))
            if job:
                result.append(job)

        return result

    def _normalise_json_job(
        self, raw: dict, subdomain: str, cv_profile: str, base_url: str, location: str
    ) -> Optional[dict]:
        external_id = str(raw.get("id") or raw.get("slug") or "")
        if not external_id:
            return None

        title = raw.get("title") or raw.get("name") or raw.get("position") or ""
        company = self._subdomain_to_name(subdomain)

        url = (
            raw.get("careersite_job_url")
            or raw.get("url")
            or f"{base_url}/jobs/{external_id}"
        )
        if url and not url.startswith("http"):
            url = urljoin(base_url, url)

        description = raw.get("body") or raw.get("description") or raw.get("pitch") or ""
        employment_type = raw.get("employment_type") or raw.get("contract") or None

        return {
            "site": self.SITE,
            "external_id": f"{subdomain}_{external_id}",
            "url": url,
            "title": title,
            "company": company,
            "location": location or "España",
            "description": description,
            "salary_raw": None,
            "contract_type": employment_type,
            "cv_profile": self._assign_cv_profile(title, cv_profile),
            "raw_data": raw,
        }

    # ------------------------------------------------------------------
    # HTML fallback
    # ------------------------------------------------------------------

    async def _fetch_html(
        self, client: httpx.AsyncClient, subdomain: str, cv_profile: str, base_url: str
    ) -> list[dict]:
        jobs: list[dict] = []
        jobs_page = f"{base_url}/jobs"

        try:
            resp = await client.get(jobs_page, timeout=20.0)
            if resp.status_code != 200:
                self._log.debug("teamtailor.html_not_200", subdomain=subdomain, status=resp.status_code)
                return []

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")

            selectors = [
                "[data-department] li",
                ".jobs-list__item",
                "[class*='job-item']",
                "li[class*='job']",
                "article[class*='job']",
            ]
            cards = []
            for sel in selectors:
                cards = soup.select(sel)
                if cards:
                    break

            if not cards:
                cards = soup.find_all("a", href=lambda h: h and "/jobs/" in h)

            for card in cards:
                try:
                    link_el = card if card.name == "a" else card.find("a", href=True)
                    href = link_el["href"] if link_el else ""
                    url = urljoin(base_url, href) if href and not href.startswith("http") else href

                    title_el = card.find(["h3", "h2", "h4"]) or card.find(class_=lambda c: c and "title" in str(c).lower())
                    title = title_el.get_text(strip=True) if title_el else card.get_text(strip=True)[:80]

                    loc_el = card.find(class_=lambda c: c and "location" in str(c).lower())
                    location = loc_el.get_text(strip=True) if loc_el else "España"

                    if not title:
                        continue

                    external_id = self._extract_id_from_url(href) or self._synthetic_id(title, subdomain)
                    jobs.append({
                        "site": self.SITE,
                        "external_id": f"{subdomain}_{external_id}",
                        "url": url or jobs_page,
                        "title": title,
                        "company": self._subdomain_to_name(subdomain),
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
            self._log.warning("teamtailor.bs4_unavailable", tip="pip install beautifulsoup4")
        except Exception as exc:
            self._log.warning("teamtailor.html_error", subdomain=subdomain, error=str(exc))

        return jobs

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_spain_or_remote(self, location: str) -> bool:
        loc = location.lower()
        return any(kw in loc for kw in SPAIN_KEYWORDS) or not loc

    def _subdomain_to_name(self, subdomain: str) -> str:
        known = {
            "decathlon-spain": "Decathlon España",
            "factorial": "Factorial",
            "paack": "Paack",
            "stuart": "Stuart",
            "amenitiz": "Amenitiz",
            "holded": "Holded",
            "woffu": "Woffu",
            "signaturit": "Signaturit",
            "deporvillage": "Deporvillage",
        }
        return known.get(subdomain, subdomain.replace("-", " ").title())

    def _extract_id_from_url(self, url: str) -> str:
        if not url:
            return ""
        parts = [p for p in url.split("/") if p]
        return parts[-1] if parts else ""

    def _synthetic_id(self, title: str, subdomain: str) -> str:
        raw = f"{self.SITE}|{subdomain}|{title.lower()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def _assign_cv_profile(self, title: str, default: str) -> str:
        t = title.lower()
        if any(kw in t for kw in ["frontend", "front-end", "react", "vue", "angular"]):
            return "frontend_dev"
        if any(kw in t for kw in ["fullstack", "full stack", "backend", "software", "developer", "engineer", "python", "java", "node"]):
            return "fullstack_dev"
        if any(kw in t for kw in ["logistics", "logística", "warehouse", "almacén", "reparto", "driver"]):
            return "logistics"
        return default
