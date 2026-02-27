# -*- coding: utf-8 -*-
"""
Base scraper: shared HTTP session, User-Agent rotation, retry logic,
and price / rating / delivery parsing for Indian e-commerce sites.
"""
from __future__ import annotations

import random
import re
import time
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from app.schemas import RawListing, SiteStatus, SiteStatusCode
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── User-Agent pool ──────────────────────────────────────────────────────────

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) "
    "Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Safari/605.1.15",
]


# ── Price / rating / delivery parsers ────────────────────────────────────────

# Indian price regex: handles ₹55,999 | Rs 1,29,999 | Rs. 55999 | bare 55999
_PRICE_RE = re.compile(
    r'(?:₹|Rs\.?\s*|INR\s*)?'       # optional currency prefix
    r'(\d{1,2}(?:,\d{2})*,\d{3}'    # lakh format  1,29,999
    r'|\d{1,3}(?:,\d{3})*'          # standard     55,999
    r'|\d+)'                         # bare         55999
    r'(?:\.\d{1,2})?'               # optional .00
)


def parse_price(text: Optional[str]) -> Optional[float]:
    """Extract first numeric price from an Indian price string."""
    if not text:
        return None
    m = _PRICE_RE.search(text.replace('\xa0', ' '))
    if not m:
        return None
    digits = m.group(1).replace(',', '')
    try:
        return float(digits)
    except ValueError:
        return None


def parse_rating(text: Optional[str]) -> Optional[float]:
    """Extract star rating float from text like '4.3 out of 5 stars'."""
    if not text:
        return None
    m = re.search(r'(\d+\.?\d*)\s*(?:out of|/)\s*5', text, re.I)
    if m:
        return min(float(m.group(1)), 5.0)
    m = re.search(r'(\d+\.?\d*)', text)
    if m:
        val = float(m.group(1))
        return val if val <= 5.0 else None
    return None


def parse_delivery_days(text: Optional[str]) -> Optional[int]:
    """Estimate delivery days from free-form text."""
    if not text:
        return None
    t = text.lower()
    if 'tomorrow' in t:
        return 1
    if 'today' in t:
        return 0
    m = re.search(r'(\d+)\s*(?:to|-)\s*(\d+)\s*day', t)
    if m:
        return int(m.group(2))  # take the max
    m = re.search(r'(\d+)\s*day', t)
    if m:
        return int(m.group(1))
    # Date-based: "Mon, 3 Mar" etc — approximate as ~3 days
    if re.search(r'(mon|tue|wed|thu|fri|sat|sun)', t):
        return 3
    return None


# ── Base Scraper ─────────────────────────────────────────────────────────────

class BaseScraper(ABC):
    """
    HTTP + BeautifulSoup scraper base class.

    Subclasses implement `scrape()` which returns a list of RawListing.
    The base class provides session management, polite delays, and retries.
    """

    MAX_RETRIES = 3
    BASE_DELAY  = (1.0, 3.0)   # random delay range between requests (seconds)
    TIMEOUT     = 15            # HTTP timeout

    def __init__(self):
        self._session: Optional[requests.Session] = None

    # ── Session ──────────────────────────────────────────────────────────

    def _get_session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._rotate_ua()
        return self._session

    def _rotate_ua(self) -> None:
        ua = random.choice(_USER_AGENTS)
        s = self._get_session()
        s.headers.update({
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        })

    # ── HTTP fetch with retries ──────────────────────────────────────────

    def fetch(self, url: str) -> Optional[BeautifulSoup]:
        """GET url → BeautifulSoup (lxml). Returns None on persistent failure."""
        session = self._get_session()

        for attempt in range(1, self.MAX_RETRIES + 1):
            self._rotate_ua()  # fresh UA each attempt
            self._polite_delay()

            try:
                logger.info("[%s] GET (attempt %d): %s",
                            self.__class__.__name__, attempt, url[:100])
                resp = session.get(url, timeout=self.TIMEOUT)

                if resp.status_code == 429:
                    wait = 2 ** attempt + random.uniform(1, 3)
                    logger.warning("[%s] 429 — backing off %.1fs",
                                   self.__class__.__name__, wait)
                    time.sleep(wait)
                    continue

                if resp.status_code >= 500:
                    wait = 2 ** attempt
                    logger.warning("[%s] %d — retrying in %ds",
                                   self.__class__.__name__, resp.status_code, wait)
                    time.sleep(wait)
                    continue

                if resp.status_code != 200:
                    logger.warning("[%s] HTTP %d for %s",
                                   self.__class__.__name__, resp.status_code, url[:80])
                    return None

                return BeautifulSoup(resp.text, "lxml")

            except requests.RequestException as e:
                logger.error("[%s] Request error (attempt %d): %s",
                             self.__class__.__name__, attempt, str(e)[:100])
                if attempt < self.MAX_RETRIES:
                    time.sleep(2 ** attempt)

        return None

    # ── Helpers ──────────────────────────────────────────────────────────

    def _polite_delay(self) -> None:
        time.sleep(random.uniform(*self.BASE_DELAY))

    @staticmethod
    def _text(el) -> str:
        """Get stripped text from a BS4 element, or empty string."""
        return el.get_text(strip=True) if el else ""

    @staticmethod
    def _select_first(card, *selectors) -> Optional[object]:
        """Try multiple CSS selectors; return first match or None."""
        for sel in selectors:
            if not sel:
                continue
            found = card.select_one(sel)
            if found:
                return found
        return None

    # ── Abstract ─────────────────────────────────────────────────────────

    @abstractmethod
    def scrape(self, query: str, max_results: int = 20) -> List[RawListing]:
        """Scrape products for the given query. Must be implemented by subclass."""
        ...

    # ── Convenience: async wrapper for pipeline integration ──────────────

    async def async_scrape(
        self,
        query: str,
        max_results: int,
        site_key: str,
        site_name: str,
    ) -> Tuple[List[RawListing], SiteStatus]:
        """
        Run synchronous `scrape()` in a thread-pool executor and return
        (listings, SiteStatus) matching the orchestrator interface.
        """
        import asyncio

        status = SiteStatus(
            marketplace_key=site_key,
            marketplace_name=site_name,
            status=SiteStatusCode.PENDING,
            message="Starting",
            listings_found=0,
        )

        try:
            loop = asyncio.get_event_loop()
            listings = await loop.run_in_executor(
                None, self.scrape, query, max_results,
            )

            if listings:
                status.status = SiteStatusCode.OK
                status.message = f"{len(listings)} listings scraped"
                status.listings_found = len(listings)
            else:
                status.status = SiteStatusCode.NO_RESULTS
                status.message = f"0 products found on {site_name}"

            return listings, status

        except Exception as e:
            logger.error("[%s] scrape() failed: %s",
                         self.__class__.__name__, str(e)[:120])
            status.status = SiteStatusCode.ERROR
            status.message = f"Error: {str(e)[:100]}"
            return [], status
