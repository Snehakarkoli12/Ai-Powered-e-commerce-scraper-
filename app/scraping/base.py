# -*- coding: utf-8 -*-
from __future__ import annotations
import asyncio
import random
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlparse, quote_plus

from playwright.async_api import Page, TimeoutError as PWTimeout

from app.schemas import RawListing, SiteStatus, SiteStatusCode
from app.marketplaces.registry import MarketplaceConfig
from app.scraping.playwright_manager import playwright_manager
from app.scraping.selector_engine import selector_engine, UNIVERSAL
from app.utils.logger import get_logger

DEBUG_DIR = Path(__file__).parent / "debug"
DEBUG_DIR.mkdir(exist_ok=True)

COOKIE_SELECTORS = [
    "button#onetrust-accept-btn-handler",
    "button[class*='accept'][class*='cookie']",
    "button[id*='accept']",
    "button[class*='accept']",
    "button:has-text('Accept all')",
    "button:has-text('Accept')",
    "button:has-text('I agree')",
    "button:has-text('Got it')",
]

_TITLE_JUNK = [
    "add to compare",
    "coming soon",
    "sponsored",
    "new arrival",
    "best seller",
    "deal of",
]


def _clean_title(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    for line in [ln.strip() for ln in raw.split("\n") if ln.strip()]:
        if (
            not any(line.lower().startswith(j) for j in _TITLE_JUNK)
            and len(line) > 5
        ):
            return line
    return None


class BaseScraper:

    def __init__(self, config: MarketplaceConfig):
        self.config  = config
        self._domain = urlparse(config.base_url).netloc.replace("www.", "")
        self.logger  = get_logger("scraper." + config.key)

    # ------------------------------------------------------------------ #
    #  Public entry point — returns (listings, status, raw_html)          #
    # ------------------------------------------------------------------ #

    async def scrape(
        self,
        search_query: str,
        max_results: int,
    ) -> Tuple[List[RawListing], SiteStatus, str]:

        page: Optional[Page] = None
        status = SiteStatus(
            marketplace_key=self.config.key,
            marketplace_name=self.config.name,
            status=SiteStatusCode.PENDING,
            message="Starting",
            listings_found=0,
        )
        raw_html = ""
        url      = self.config.search_url_pattern.format(
            query=quote_plus(search_query)
        )

        try:
            # ---------------------------------------------------------- #
            # Step 1 — Navigate                                           #
            # ---------------------------------------------------------- #
            self.logger.info("GET %s", url)
            page = await playwright_manager.new_page(self._domain)
            await page.goto(
                url,
                wait_until=self.config.wait_strategy,
                timeout=25000,
            )
            await playwright_manager.random_delay(*self.config.request_delay_ms)
            await self._wait_for_content(page)
            await self._dismiss_cookies(page)
            raw_html = await page.content()

            # ---------------------------------------------------------- #
            # Step 2 — Bot challenge check + one retry                    #
            # ---------------------------------------------------------- #
            if self._is_bot_challenge(raw_html):
                self.logger.warning(
                    "Bot challenge on %s — retrying with fresh context",
                    self.config.name,
                )
                await self._save_debug(page, "bot_challenge")
                await page.close()
                page = None

                await playwright_manager.reset_context(self._domain)
                await asyncio.sleep(random.uniform(2.0, 4.0))

                page     = await playwright_manager.new_page(self._domain)
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await playwright_manager.random_delay(1500, 3000)
                await self._wait_for_content(page)
                raw_html = await page.content()

                if self._is_bot_challenge(raw_html):
                    status.status  = SiteStatusCode.BOT_CHALLENGE
                    status.message = (
                        "Bot challenge on "
                        + self.config.name
                        + " (retry also blocked)"
                    )
                    self.logger.warning(
                        "Bot challenge persists after retry: %s", self.config.name
                    )
                    await self._save_debug(page, "bot_challenge_retry")
                    return [], status, raw_html

                self.logger.info(
                    "Bot challenge resolved after retry: %s", self.config.name
                )

            # ---------------------------------------------------------- #
            # Step 3 — Scroll to trigger lazy-loaded content              #
            # ---------------------------------------------------------- #
            if self.config.needs_scroll:
                await self._human_scroll(page)

            # ---------------------------------------------------------- #
            # Step 4 — Resolve product-card container                     #
            # Priority: YAML selector -> universal patterns -> LLM        #
            # ---------------------------------------------------------- #
            container_sel = await selector_engine.resolve_container(
                page,
                self._domain,
                self.config.selectors.search_results_container,
                None,
            )

            # Retry once after networkidle
            if not container_sel:
                self.logger.info(
                    "Container not found on first pass — waiting for networkidle"
                )
                try:
                    await page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                await self._human_scroll(page)
                container_sel = await selector_engine.resolve_container(
                    page,
                    self._domain,
                    self.config.selectors.search_results_container,
                    None,
                )

            # LLM selector discovery as last resort
            if not container_sel and raw_html:
                self.logger.info(
                    "All selectors failed — attempting LLM discovery for %s",
                    self.config.key,
                )
                try:
                    from app.agents.llm_extractor import llm_discover_selectors
                    discovered = await llm_discover_selectors(raw_html, self.config.key)
                    if discovered and discovered.get("container"):
                        sel   = discovered["container"]
                        elems = await page.query_selector_all(sel)
                        if len(elems) >= 1:
                            container_sel = sel
                            selector_engine._save(self._domain, "container", sel)
                            for field in [
                                "title", "price", "original_price", "listing_url"
                            ]:
                                if discovered.get(field):
                                    selector_engine._save(
                                        self._domain, field, discovered[field]
                                    )
                            self.logger.info(
                                "LLM found container: '%s' (%d items)",
                                sel, len(elems),
                            )
                except Exception as llm_err:
                    self.logger.error("LLM selector discovery error: %s", llm_err)

            if not container_sel:
                tried = len(UNIVERSAL.get("container", []))
                status.status  = SiteStatusCode.SELECTOR_ERROR
                status.message = (
                    "No container found — tried YAML + "
                    + str(tried)
                    + " universal patterns + LLM. "
                    + "Debug HTML: "
                    + self.config.key
                    + "_no_container_*.html"
                )
                self.logger.warning(status.message)
                await self._save_debug(page, "no_container")
                return [], status, raw_html

            # ---------------------------------------------------------- #
            # Step 5 — Extract cards                                      #
            # ---------------------------------------------------------- #
            cards = await page.query_selector_all(container_sel)
            self.logger.debug(
                "%d cards found (selector: %s)", len(cards), container_sel
            )

            if not cards:
                status.status  = SiteStatusCode.NO_RESULTS
                status.message = (
                    "Container '"
                    + container_sel
                    + "' found but contains 0 cards"
                )
                await self._save_debug(page, "zero_cards")
                return [], status, raw_html

            listings: List[RawListing] = []
            for idx, card in enumerate(cards[:max_results]):
                try:
                    listing = await self.extract_from_card(card, page)
                    if listing and listing.title:
                        listings.append(listing)
                except Exception as card_err:
                    self.logger.error(
                        "Card %d extraction error [%s]: %s",
                        idx, self.config.key, card_err,
                    )

            status.status         = SiteStatusCode.OK
            status.message        = "Scraped " + str(len(listings)) + " listings"
            status.listings_found = len(listings)
            self.logger.info(
                "%s: %d listings scraped", self.config.name, len(listings)
            )
            return listings, status, raw_html

        except PWTimeout as timeout_err:
            status.status  = SiteStatusCode.TIMEOUT
            status.message = "Timeout: " + str(timeout_err)
            self.logger.warning("Timeout on %s: %s", self.config.key, timeout_err)
            if page:
                await self._save_debug(page, "timeout")
            return [], status, raw_html

        except Exception as err:
            status.status  = SiteStatusCode.ERROR
            status.message = "Error: " + str(err)
            self.logger.exception("Scrape error on %s", self.config.key)
            if page:
                await self._save_debug(page, "error")
            return [], status, raw_html

        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass

    # ------------------------------------------------------------------ #
    #  Card field extraction                                              #
    # ------------------------------------------------------------------ #

    async def extract_from_card(
        self, card, page: Page
    ) -> Optional[RawListing]:
        s = self.config.selectors
        d = self._domain

        raw_title = await selector_engine.get_text(
            card, d, "title", s.title.primary, s.title.fallback
        )
        title = _clean_title(raw_title)
        if not title:
            return None

        price_text = await selector_engine.get_text(
            card, d, "price",
            s.price.primary, s.price.fallback,
        )
        original_price_text = await selector_engine.get_text(
            card, d, "original_price",
            s.original_price.primary, s.original_price.fallback,
        )
        rating_text = await selector_engine.get_text(
            card, d, "rating",
            s.rating.primary, s.rating.fallback,
        )
        review_count_text = await selector_engine.get_text(
            card, d, "review_count",
            s.review_count.primary, s.review_count.fallback,
        )
        delivery_text = await selector_engine.get_text(
            card, d, "delivery",
            s.delivery.primary, s.delivery.fallback,
        )
        shipping_text = await selector_engine.get_text(
            card, d, "shipping",
            s.shipping.primary, s.shipping.fallback,
        )
        seller_primary  = s.seller.primary  if s.seller else None
        seller_fallback = s.seller.fallback if s.seller else None
        seller_text = await selector_engine.get_text(
            card, d, "seller", seller_primary, seller_fallback
        )
        listing_url = await selector_engine.get_attr(
            card, d, "listing_url", "href",
            s.listing_url.primary, s.listing_url.fallback,
        )
        if listing_url and not listing_url.startswith("http"):
            listing_url = self.config.base_url.rstrip("/") + listing_url

        return RawListing(
            platform_key=self.config.key,
            listing_url=listing_url or "",
            title=title,
            price_text=price_text,
            original_price_text=original_price_text,
            rating_text=rating_text,
            review_count_text=review_count_text,
            delivery_text=delivery_text,
            shipping_text=shipping_text,
            seller_text=seller_text,
        )

    # ------------------------------------------------------------------ #
    #  Page helpers                                                        #
    # ------------------------------------------------------------------ #

    async def _wait_for_content(self, page: Page):
        if self.config.ready_selector:
            try:
                await page.wait_for_selector(
                    self.config.ready_selector, timeout=8000
                )
                return
            except Exception:
                pass
        for sel in ["main", "#root", "#app", ".container", "body"]:
            try:
                elem = await page.query_selector(sel)
                if elem:
                    await asyncio.sleep(1.5)
                    return
            except Exception:
                continue

    def _is_bot_challenge(self, html: str) -> bool:
        low = html.lower()
        return any(
            phrase.lower() in low
            for phrase in self.config.bot_detection_phrases
        )

    async def _dismiss_cookies(self, page: Page):
        for sel in COOKIE_SELECTORS:
            try:
                btn = await page.query_selector(sel)
                if btn:
                    await btn.click()
                    await playwright_manager.random_delay(400, 800)
                    return
            except Exception:
                continue

    async def _human_scroll(self, page: Page):
        for pos in [300, 700, 1100, 500, 0]:
            try:
                await page.evaluate(
                    "window.scrollTo(0, " + str(pos) + ")"
                )
                await asyncio.sleep(random.uniform(0.15, 0.35))
            except Exception:
                pass

    async def _save_debug(self, page: Page, reason: str):
        ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = self.config.key + "_" + reason + "_" + ts + ".html"
        path  = DEBUG_DIR / fname
        try:
            content = await page.content()
            path.write_text(content, encoding="utf-8", errors="replace")
            self.logger.info("Debug HTML saved: %s", fname)
        except Exception as save_err:
            self.logger.error("Failed to save debug HTML: %s", save_err)
