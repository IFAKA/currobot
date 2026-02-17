"""Generic parameterised Workday ATS scraper — config-driven."""
from __future__ import annotations

import hashlib
from typing import Any, Optional

import httpx
import structlog

from backend.scrapers.base import BaseScraper

log = structlog.get_logger(__name__)

# Default Workday tenants with Spain presence
DEFAULT_COMPANIES: dict[str, dict[str, str]] = {
    "elcorteingles": {
        "tenant": "elcorteingles",
        "base_url": "https://elcorteingles.wd3.myworkdayjobs.com",
        "cv_profile": "cashier",
        "name": "El Corte Inglés",
    },
    "inditex": {
        "tenant": "inditex",
        "base_url": "https://inditex.wd3.myworkdayjobs.com",
        "cv_profile": "stocker",
        "name": "Inditex",
    },
    "carrefour": {
        "tenant": "carrefoures",
        "base_url": "https://carrefoures.wd3.myworkdayjobs.com",
        "cv_profile": "cashier",
        "name": "Carrefour España",
    },
    "dia": {
        "tenant": "dia",
        "base_url": "https://dia.wd3.myworkdayjobs.com",
        "cv_profile": "cashier",
        "name": "Dia Supermercados",
    },
    "mediamarkt": {
        "tenant": "mediamarkt",
        "base_url": "https://mediamarkt.wd3.myworkdayjobs.com",
        "cv_profile": "cashier",
        "name": "MediaMarkt España",
    },
}


class WorkdayScraper(BaseScraper):
    """Scrape Workday ATS for retail/logistics companies in Spain."""

    SITE = "workday"

    HEADERS = {
        "Accept": "application/json",
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
        companies = dict(DEFAULT_COMPANIES)

        # Merge with DB-configured sources
        try:
            async with self.db_session_factory() as db:
                from backend.database.crud import list_company_sources
                sources = await list_company_sources(db, enabled_only=True)
                for source in sources:
                    if source.scraper_type == "workday":
                        extra = source.extra_config or {}
                        slug = extra.get("slug") or source.company_name.lower().replace(" ", "")
                        companies[slug] = {
                            "tenant": extra.get("tenant", slug),
                            "base_url": extra.get("base_url", f"https://{slug}.wd3.myworkdayjobs.com"),
                            "cv_profile": source.cv_profile,
                            "name": source.company_name,
                        }
        except Exception as exc:
            self._log.warning("workday.db_sources_error", error=str(exc))

        all_jobs: list[dict] = []

        async with httpx.AsyncClient(
            headers=self.HEADERS,
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            for slug, meta in companies.items():
                self._log.info("workday.fetching", slug=slug)
                jobs = await self._fetch_company(client, slug, meta)
                all_jobs.extend(jobs)
                self._log.info("workday.company_done", slug=slug, found=len(jobs))
                await self._rate_limit()

        # Deduplicate
        seen: set[str] = set()
        unique: list[dict] = []
        for job in all_jobs:
            eid = job.get("external_id", "")
            if eid not in seen:
                seen.add(eid)
                unique.append(job)

        self._log.info("workday.total", total=len(unique))
        return unique

    # ------------------------------------------------------------------
    # Per-company fetch
    # ------------------------------------------------------------------

    async def _fetch_company(
        self, client: httpx.AsyncClient, slug: str, meta: dict
    ) -> list[dict]:
        tenant = meta["tenant"]
        base_url = meta["base_url"]
        cv_profile = meta.get("cv_profile", "cashier")
        company_name = meta.get("name", slug.capitalize())

        jobs: list[dict] = []

        # Strategy 1: Workday job search service (unauthenticated)
        api_jobs = await self._fetch_via_api(client, tenant, base_url, cv_profile, company_name)
        if api_jobs:
            return api_jobs

        # Strategy 2: Workday public XML/HTML
        self._log.debug("workday.api_failed_trying_html", slug=slug)
        html_jobs = await self._fetch_via_html(client, tenant, base_url, cv_profile, company_name)
        jobs.extend(html_jobs)

        return jobs

    # ------------------------------------------------------------------
    # API strategy
    # ------------------------------------------------------------------

    async def _fetch_via_api(
        self, client: httpx.AsyncClient, tenant: str, base_url: str, cv_profile: str, company_name: str
    ) -> list[dict]:
        jobs: list[dict] = []
        offset = 0
        limit = 20

        while True:
            url = (
                f"{base_url}/wday/authgwy/{tenant}/"
                f"job-search-service/jobs?offset={offset}&limit={limit}"
            )
            try:
                resp = await client.get(url, timeout=20.0)
                if resp.status_code in (401, 403, 404):
                    self._log.debug("workday.api_no_access", tenant=tenant, status=resp.status_code)
                    return []
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (401, 403, 404):
                    return []
                self._log.warning("workday.api_error", tenant=tenant, error=str(exc))
                return jobs
            except Exception as exc:
                self._log.debug("workday.api_exception", tenant=tenant, error=str(exc))
                return jobs

            page_jobs = self._parse_api_response(data, tenant, cv_profile, company_name, base_url)
            if not page_jobs:
                break

            jobs.extend(page_jobs)
            offset += limit

            if len(page_jobs) < limit:
                break

            await self._rate_limit()

        return jobs

    def _parse_api_response(
        self, data: Any, tenant: str, cv_profile: str, company_name: str, base_url: str
    ) -> list[dict]:
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
            job = self._normalise_job(raw, tenant, cv_profile, company_name, base_url)
            if job:
                result.append(job)
        return result

    def _normalise_job(
        self, raw: dict, tenant: str, cv_profile: str, company_name: str, base_url: str
    ) -> Optional[dict]:
        external_id = str(
            raw.get("bulletinId")
            or raw.get("externalId")
            or raw.get("id")
            or raw.get("jobPostingId")
            or ""
        )
        if not external_id:
            title_raw = raw.get("title") or raw.get("jobTitle") or ""
            external_id = self._synthetic_id(title_raw, tenant)

        title = raw.get("title") or raw.get("jobTitle") or ""
        location = raw.get("locationsText") or raw.get("location") or raw.get("primaryLocation") or "España"
        if isinstance(location, dict):
            location = location.get("descriptor") or location.get("name") or "España"

        url_path = raw.get("externalPath") or raw.get("url") or ""
        url = (
            (base_url + url_path)
            if url_path and not url_path.startswith("http")
            else url_path or f"{base_url}/en-US/{tenant}/job/{external_id}"
        )

        description = raw.get("jobDescription") or raw.get("description") or ""
        schedule = raw.get("jobSchedule")
        contract_type = schedule.get("descriptor") if isinstance(schedule, dict) else None

        return {
            "site": self.SITE,
            "external_id": f"{tenant}_{external_id}",
            "url": url,
            "title": title,
            "company": company_name,
            "location": location,
            "description": description,
            "salary_raw": None,
            "contract_type": contract_type,
            "cv_profile": self._assign_cv_profile(title, cv_profile),
            "raw_data": raw,
        }

    # ------------------------------------------------------------------
    # HTML strategy
    # ------------------------------------------------------------------

    async def _fetch_via_html(
        self, client: httpx.AsyncClient, tenant: str, base_url: str, cv_profile: str, company_name: str
    ) -> list[dict]:
        jobs: list[dict] = []
        page = 0
        limit = 20

        while True:
            url = f"{base_url}/en-US/{tenant}/jobs?offset={page * limit}&limit={limit}"
            try:
                resp = await client.get(url, timeout=20.0)
                if resp.status_code != 200:
                    break
                html = resp.text
            except Exception as exc:
                self._log.warning("workday.html_error", tenant=tenant, error=str(exc))
                break

            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, "html.parser")
                cards = soup.select("[data-automation-id='jobPostingsList'] li, .job-posting-item, li[class*='job']")
                if not cards:
                    break

                for card in cards:
                    try:
                        title_el = card.find(["h3", "h2", "a"])
                        title = title_el.get_text(strip=True) if title_el else ""
                        link_el = card.find("a", href=True)
                        href = link_el["href"] if link_el else ""
                        if not href.startswith("http"):
                            href = base_url + href
                        loc_el = card.find(class_=lambda c: c and "location" in str(c).lower())
                        location = loc_el.get_text(strip=True) if loc_el else "España"
                        external_id = self._synthetic_id(title, tenant)
                        if title:
                            jobs.append({
                                "site": self.SITE,
                                "external_id": f"{tenant}_{external_id}",
                                "url": href or url,
                                "title": title,
                                "company": company_name,
                                "location": location,
                                "description": None,
                                "salary_raw": None,
                                "contract_type": None,
                                "cv_profile": self._assign_cv_profile(title, cv_profile),
                                "raw_data": {"title": title},
                            })
                    except Exception:
                        pass

                if len(cards) < limit:
                    break
                page += 1
                await self._rate_limit()

            except ImportError:
                self._log.warning("workday.bs4_unavailable")
                break
            except Exception as exc:
                self._log.warning("workday.html_parse_error", tenant=tenant, error=str(exc))
                break

        return jobs

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _synthetic_id(self, title: str, tenant: str) -> str:
        raw = f"{self.SITE}|{tenant}|{title.lower()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def _assign_cv_profile(self, title: str, default: str) -> str:
        t = title.lower()
        if any(kw in t for kw in ["cajero", "cajera", "dependiente", "atención al cliente", "cashier"]):
            return "cashier"
        if any(kw in t for kw in ["reponedor", "almacén", "almacen", "stock", "mozo", "operario"]):
            return "stocker"
        if any(kw in t for kw in ["logística", "logistica", "transporte", "reparto"]):
            return "logistics"
        return default
