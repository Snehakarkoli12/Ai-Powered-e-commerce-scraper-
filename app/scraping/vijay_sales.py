# -*- coding: utf-8 -*-
"""
Vijay Sales scraper — Playwright fetch + BeautifulSoup parse.

Uses Playwright (stealth Chromium) to fetch the page HTML (Vijay Sales
blocks plain HTTP), then parses Adobe-AEM product cards with CSS
selectors via BeautifulSoup. No LLM is needed.
"""
from __future__ import annotations

import asyncio
import random
import re
from typing import List, Optional, Tuple
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from app.schemas import RawListing, SiteStatus, SiteStatusCode
from app.scraping.base import parse_price, parse_rating
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_BASE_URL = "https://www.vijaysales.com"
_SEARCH_URL = "https://www.vijaysales.com/search-listing?q={query}"

_BOT_PHRASES = [
    "access denied",
    "unusual traffic",
    "blocked",
    "captcha",
]

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

_STEALTH_JS = """
() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => false });
    Object.defineProperty(navigator, 'plugins', {
        get: () => {
            const p = [
                { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
                { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
                { name: 'Native Client', filename: 'internal-nacl-plugin' },
            ]; p.length = 3; return p;
        }
    });
    Object.defineProperty(navigator, 'languages', { get: () => ['en-IN', 'en-US', 'en'] });
    Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
    Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
    Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
    window.chrome = {
        runtime: { id: undefined },
        loadTimes: function() {},
        csi: function() {},
        app: { isInstalled: false },
    };
}
"""

# Multiple strategies for finding product cards (verified from live page)
_CARD_STRATEGIES = [
    "div.product-card__inner",
    "div[class*='product-card__inner']",
    "div[class*='product-card']",
    "li.productcollection__item",
    "div.productcollection__item",
    "div[class*='productCard']",
    "div[data-product]",
]


class VijaySalesScraper:
    """
    Scrape Vijay Sales: Playwright fetches (bypasses blocks), BS4 parses.
    No LLM needed — uses CSS selectors for Adobe-AEM product cards.
    """

    async def async_scrape(
        self,
        query: str,
        max_results: int,
        site_key: str,
        site_name: str,
    ) -> Tuple[List[RawListing], SiteStatus]:
        """Pipeline-compatible async entry point."""
        status = SiteStatus(
            marketplace_key=site_key,
            marketplace_name=site_name,
            status=SiteStatusCode.PENDING,
            message="Starting",
            listings_found=0,
        )

        try:
            listings = await self._scrape_async(query, max_results)

            if listings:
                status.status = SiteStatusCode.OK
                status.message = f"{len(listings)} listings scraped"
                status.listings_found = len(listings)
            else:
                status.status = SiteStatusCode.NO_RESULTS
                status.message = f"0 products found on {site_name}"

            return listings, status

        except Exception as e:
            logger.error("[VijaySalesScraper] scrape failed: %s", str(e)[:120])
            status.status = SiteStatusCode.ERROR
            status.message = f"Error: {str(e)[:100]}"
            return [], status

    async def _scrape_async(self, query: str, max_results: int) -> List[RawListing]:
        """Fetch via Playwright, parse via BeautifulSoup."""
        url = _SEARCH_URL.format(query=quote_plus(query))

        for attempt in range(1, 3):
            html = await self._fetch_with_playwright(url, attempt)

            if not html or len(html.strip()) < 200:
                logger.warning("[VijaySalesScraper] Empty page (attempt %d)", attempt)
                if attempt < 2:
                    await asyncio.sleep(random.uniform(2, 4))
                continue

            soup = BeautifulSoup(html, "lxml")

            # Bot check
            page_lower = soup.get_text(" ", strip=True).lower()
            bot_found = None
            for phrase in _BOT_PHRASES:
                if phrase in page_lower:
                    bot_found = phrase
                    break
            if bot_found:
                logger.warning("[VijaySalesScraper] Bot challenge (attempt %d): '%s'",
                               attempt, bot_found)
                if attempt < 2:
                    await asyncio.sleep(random.uniform(3, 6))
                continue

            listings = self._parse_results(soup, max_results)

            if listings:
                return listings
            elif attempt < 2:
                logger.info("[VijaySalesScraper] 0 listings, retrying...")
                await asyncio.sleep(random.uniform(2, 4))

        return []

    # ── Playwright fetch ─────────────────────────────────────────────────

    async def _fetch_with_playwright(self, url: str, attempt: int) -> str:
        from playwright.async_api import async_playwright

        ua = random.choice(_USER_AGENTS)
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=settings.playwright_headless,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-infobars",
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--no-sandbox",
                    ],
                )
                ctx = await browser.new_context(
                    user_agent=ua,
                    viewport={"width": 1366, "height": 768},
                    locale="en-IN",
                    timezone_id="Asia/Kolkata",
                    bypass_csp=True,
                    extra_http_headers={
                        "Accept-Language": "en-IN,en;q=0.9",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    },
                )
                await ctx.add_init_script(_STEALTH_JS)
                page = await ctx.new_page()

                # Block heavy resources
                await page.route(
                    "**/*",
                    lambda route: route.abort()
                    if route.request.resource_type in ("font", "media", "image")
                    else route.continue_(),
                )

                logger.info("[VijaySalesScraper] Navigating (attempt %d): %s",
                            attempt, url[:80])
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(4.0 + random.uniform(0.5, 1.5))

                # Scroll to trigger lazy loading
                for pct in [0.3, 0.5, 0.7]:
                    await page.evaluate(
                        f"window.scrollTo(0, document.body.scrollHeight * {pct})"
                    )
                    await asyncio.sleep(0.4 + random.uniform(0.1, 0.4))

                html = await page.content()
                logger.info("[VijaySalesScraper] Got %d chars of HTML", len(html))

                await browser.close()
                return html

        except Exception as e:
            logger.error("[VijaySalesScraper] Playwright error (attempt %d): %s",
                         attempt, str(e)[:120])
            return ""

    # ── BS4 parsing ──────────────────────────────────────────────────────

    def _parse_results(self, soup: BeautifulSoup, max_results: int) -> List[RawListing]:
        # Try multiple card strategies
        cards = []
        used_strategy = None
        for strategy in _CARD_STRATEGIES:
            found = soup.select(strategy)
            if len(found) >= 2:
                cards = found
                used_strategy = strategy
                break

        if not cards:
            # Last resort: find divs with price-like text
            all_divs = soup.find_all("div", class_=True)
            for div in all_divs:
                text = div.get_text(" ", strip=True)
                if re.search(r'₹[\d,]+', text) and len(text) < 500:
                    cards.append(div)
            if cards:
                used_strategy = "fallback (price-containing divs)"

        if not cards:
            page_text = soup.get_text(" ", strip=True)
            logger.warning("[VijaySalesScraper] No product cards found. "
                           "Snippet: %s", page_text[:200])
            return []

        logger.info("[VijaySalesScraper] Found %d cards via '%s'",
                    len(cards), used_strategy)

        listings: List[RawListing] = []
        for card in cards[:max_results]:
            try:
                listing = self._parse_card(card)
                if listing:
                    listings.append(listing)
            except Exception as e:
                logger.debug("[VijaySalesScraper] Card parse error: %s", str(e)[:80])

        logger.info(
            "[VijaySalesScraper] Extracted %d listings (%d with price)",
            len(listings), sum(1 for l in listings if l.price_text),
        )
        return listings

    def _parse_card(self, card) -> Optional[RawListing]:
        # Title
        title_el = _sel(card,
                        "div.product-name", "div[class*='product-name']",
                        "p.product-name", "div[class*='productName']",
                        "p[class*='productName']", "a[class*='productName']",
                        "h3[class*='title'] a", "a[title]")
        title = _text(title_el)

        if not title:
            link = card.select_one("a[title]")
            if link:
                title = link.get("title", "")

        if not title or len(title) < 5:
            return None

        # URL
        url_el = _sel(card, "a.product-card__link", "a[href*='/product']",
                      "a[href*='/buy']", "a[href]")
        listing_url = ""
        if url_el and url_el.get("href"):
            listing_url = urljoin(_BASE_URL, url_el["href"])

        # Price
        price_el = _sel(card,
                        ".discountedPrice", "div[class*='discountedPrice']",
                        "span[class*='discountedPrice']",
                        "div[class*='selling-price']", "p[class*='selling-price']",
                        "span[class*='selling-price']", "span[class*='price']")
        price_text = _text(price_el) if price_el else None

        if not price_text or not parse_price(price_text):
            card_text = card.get_text(" ", strip=True)
            m = re.search(r'₹\s*[\d,]+(?:\.\d{2})?', card_text)
            if m:
                price_text = m.group(0)

        # MRP
        mrp_el = _sel(card,
                       ".originalPrice", "span[class*='originalPrice']",
                       "span[class*='mrp']", "p[class*='mrp']",
                       "div[class*='mrp']", "del", "s")
        original_price_text = _text(mrp_el) if mrp_el else None

        # Rating
        rating_el = _sel(card, ".stars", ".product__title--reviews-star",
                         "div[class*='rating'] span",
                         "span[class*='rating']", "div[class*='star']")
        rating_text = None
        if rating_el:
            parsed = parse_rating(_text(rating_el))
            if parsed is not None:
                rating_text = str(parsed)

        # Review count
        review_el = _sel(card, "span[class*='count']", "span[class*='review']")
        review_count_text = None
        if review_el:
            m = re.search(r'[\d,]+', _text(review_el))
            if m:
                review_count_text = m.group(0)

        return RawListing(
            platform_key="vijay_sales",
            listing_url=listing_url,
            title=title,
            price_text=price_text,
            original_price_text=original_price_text,
            rating_text=rating_text,
            review_count_text=review_count_text,
            delivery_text=None,
            shipping_text=None,
            seller_text="Vijay Sales",
        )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _text(el) -> str:
    return el.get_text(strip=True) if el else ""

def _sel(card, *selectors):
    for sel in selectors:
        if sel:
            found = card.select_one(sel)
            if found:
                return found
    return None