# -*- coding: utf-8 -*-
"""
Amazon India scraper — Playwright fetch + BeautifulSoup parse.

Uses Playwright (stealth Chromium) to fetch the page HTML (Amazon blocks
plain HTTP with 503), then parses product cards with CSS selectors via
BeautifulSoup. No LLM is needed — structured data is extracted directly.
"""
from __future__ import annotations

import asyncio
import random
import re
from typing import List, Optional, Tuple
from urllib.parse import quote_plus, urljoin, urlparse, unquote

from bs4 import BeautifulSoup

from app.schemas import RawListing, SiteStatus, SiteStatusCode
from app.scraping.base import parse_price, parse_rating
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_BASE_URL = "https://www.amazon.in"
_SEARCH_URL = "https://www.amazon.in/s?k={query}&i=electronics&s=review-rank"

_BOT_PHRASES = [
    "enter the characters you see below",
    "sorry, we just need to make sure",
    "type the characters you see in this image",
    "unusual traffic",
    "to discuss automated access",
    "robot",
]

_SLUG_NOISE = {
    "dp", "ref", "sr", "qid", "keywords", "crid", "sprefix",
    "encoding", "psc", "tag", "linkcode", "camp", "creative",
    "creativesin", "th", "smid", "spla", "www", "amazon", "in",
}

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]


# ── Stealth JS (reused from sgai_scraper) ────────────────────────────────────

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


class AmazonScraper:
    """
    Scrape Amazon India: Playwright fetches (bypasses 503), BS4 parses.
    No LLM needed — uses CSS selectors directly.
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
            logger.error("[AmazonScraper] scrape failed: %s", str(e)[:120])
            status.status = SiteStatusCode.ERROR
            status.message = f"Error: {str(e)[:100]}"
            return [], status

    async def _scrape_async(self, query: str, max_results: int) -> List[RawListing]:
        """Fetch via Playwright, parse via BeautifulSoup."""
        url = _SEARCH_URL.format(query=quote_plus(query))

        for attempt in range(1, 3):
            html = await self._fetch_with_playwright(url, attempt)

            if not html or len(html.strip()) < 200:
                logger.warning("[AmazonScraper] Empty page (attempt %d)", attempt)
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
                logger.warning("[AmazonScraper] Bot challenge (attempt %d): '%s'",
                               attempt, bot_found)
                if attempt < 2:
                    await asyncio.sleep(random.uniform(3, 6))
                continue

            # Parse product cards
            listings = self._parse_results(soup, max_results)

            if listings:
                return listings
            elif attempt < 2:
                logger.info("[AmazonScraper] 0 listings, retrying...")
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

                logger.info("[AmazonScraper] Navigating (attempt %d): %s",
                            attempt, url[:80])
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3.0 + random.uniform(0.5, 1.5))

                # Scroll to trigger lazy loading
                for pct in [0.3, 0.5, 0.7]:
                    await page.evaluate(
                        f"window.scrollTo(0, document.body.scrollHeight * {pct})"
                    )
                    await asyncio.sleep(0.4 + random.uniform(0.1, 0.4))

                html = await page.content()
                logger.info("[AmazonScraper] Got %d chars of HTML", len(html))

                await browser.close()
                return html

        except Exception as e:
            logger.error("[AmazonScraper] Playwright error (attempt %d): %s",
                         attempt, str(e)[:120])
            return ""

    # ── BS4 parsing ──────────────────────────────────────────────────────

    def _parse_results(self, soup: BeautifulSoup, max_results: int) -> List[RawListing]:
        cards = soup.select("[data-component-type='s-search-result']")
        if not cards:
            cards = soup.select("div[data-asin]:not([data-asin=''])")
            logger.info("[AmazonScraper] Fallback selector: %d cards", len(cards))

        logger.info("[AmazonScraper] Found %d product cards", len(cards))

        listings: List[RawListing] = []
        for card in cards[:max_results]:
            try:
                listing = self._parse_card(card)
                if listing:
                    listings.append(listing)
            except Exception as e:
                logger.debug("[AmazonScraper] Card parse error: %s", str(e)[:80])

        logger.info(
            "[AmazonScraper] Extracted %d listings (%d with price)",
            len(listings), sum(1 for l in listings if l.price_text),
        )
        return listings

    def _parse_card(self, card) -> Optional[RawListing]:
        # Title
        title_el = _sel(card, "h2 .a-text-normal", "h2 a span", "h2 a", "h2")
        title = _text(title_el)

        # URL
        url_el = _sel(card, "h2 a[href]", "a.a-link-normal[href*='/dp/']",
                       "a[href*='/dp/']")
        listing_url = ""
        if url_el and url_el.get("href"):
            listing_url = urljoin(_BASE_URL, url_el["href"].split("/ref=")[0])

        if not title and listing_url:
            title = _title_from_slug(listing_url)
        if not title or len(title) < 5:
            return None

        # Price
        price_el = _sel(card, ".a-price .a-offscreen", ".a-price-whole")
        price_text = _text(price_el)
        if not price_text or not parse_price(price_text):
            whole_el = card.select_one(".a-price-whole")
            frac_el  = card.select_one(".a-price-fraction")
            if whole_el:
                whole = _text(whole_el).rstrip(".")
                frac  = _text(frac_el) if frac_el else "00"
                price_text = f"₹{whole}.{frac}"

        # MRP
        mrp_el = _sel(card, ".a-text-price .a-offscreen", ".a-text-price span")
        original_price_text = _text(mrp_el) or None

        # Rating
        rating_el = _sel(card, ".a-icon-star-small .a-icon-alt",
                         "[aria-label*='out of 5 stars']", "i.a-icon-star-small")
        rating_text = None
        if rating_el:
            raw = rating_el.get("aria-label") or _text(rating_el)
            parsed = parse_rating(raw)
            if parsed is not None:
                rating_text = str(parsed)

        # Review count
        review_el = _sel(card, ".a-size-base.s-underline-text",
                         "[aria-label*='ratings']", "span.a-size-base")
        review_count_text = None
        if review_el:
            m = re.search(r'[\d,]+', _text(review_el).replace('\xa0', ''))
            if m:
                review_count_text = m.group(0)

        # Delivery
        delivery_text = _extract_delivery(card)

        # Shipping
        shipping_text = _extract_shipping(card, price_text)

        return RawListing(
            platform_key="amazon",
            listing_url=listing_url,
            title=title,
            price_text=price_text or None,
            original_price_text=original_price_text,
            rating_text=rating_text,
            review_count_text=review_count_text,
            delivery_text=delivery_text,
            shipping_text=shipping_text,
            seller_text="Amazon.in",
        )


# ── Helper functions ─────────────────────────────────────────────────────────

def _text(el) -> str:
    return el.get_text(strip=True) if el else ""

def _sel(card, *selectors):
    for sel in selectors:
        if sel:
            found = card.select_one(sel)
            if found:
                return found
    return None

def _extract_delivery(card) -> Optional[str]:
    for sel in [
        "[data-cy='delivery-recipe-content'] .a-text-bold",
        ".a-color-base.a-text-bold",
        "span[data-component-type='s-delivery-badge']",
        "[aria-label*='delivery']",
    ]:
        el = card.select_one(sel)
        if el:
            text = _text(el)
            if text and len(text) > 2:
                return text
    prime = card.select_one("i.a-icon-prime, [aria-label*='Prime']")
    if prime:
        return "Prime — 2 days"
    return "5 days (estimated)"

def _extract_shipping(card, price_text: Optional[str]) -> Optional[str]:
    prime = card.select_one("i.a-icon-prime, [aria-label*='Prime']")
    if prime:
        return "Free (Prime)"
    if price_text:
        val = parse_price(price_text)
        if val and val >= 499:
            return "Free delivery"
    return None

def _title_from_slug(url: str) -> str:
    try:
        path = urlparse(url).path
        parts = path.strip("/").split("/")
        if parts:
            slug = unquote(parts[0])
            words = slug.replace("-", " ").split()
            cleaned = [w for w in words if w.lower() not in _SLUG_NOISE and len(w) > 1]
            return " ".join(cleaned)
    except Exception:
        pass
    return ""