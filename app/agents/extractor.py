# -*- coding: utf-8 -*-
"""
Extractor agent: RawListing -> NormalizedOffer
Parses price, delivery, rating from text fields.
"""
from __future__ import annotations
import re
from typing import Optional, Tuple

from app.schemas import PipelineState, RawListing, NormalizedOffer
from app.marketplaces.registry import marketplace_registry
from app.utils.logger import get_logger

logger = get_logger(__name__)


# -- Price parser -------------------------------------------------------------

# Handles: Rs 55,999 | Rs.55999 | 55,999 | 1,29,999 (Indian lakhs) | 55999.00
_PRICE_RE = re.compile(r"[\d,]+(?:\.\d{1,2})?")

def _parse_price(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    # Strip all currency markers robustly
    cleaned = (
        text
        .replace("\u20b9", "")    # actual rupee sign
        .replace("Rs.", "")
        .replace("Rs", "")
        .replace("INR", "")
        .replace("MRP", "")
        .replace(",", "")
        .strip()
    )
    m = _PRICE_RE.search(cleaned)
    if not m:
        return None
    try:
        val = float(m.group().replace(",", ""))
        # Broad range: covers accessories (Rs.100) to premium electronics (Rs.5,00,000)
        return val if 50.0 <= val <= 500000.0 else None
    except ValueError:
        return None


# -- Rating parser ------------------------------------------------------------

_RATING_RE = re.compile(r"(\d+(?:\.\d)?)")

def _parse_rating(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    m = _RATING_RE.search(text)
    if not m:
        return None
    try:
        val = float(m.group(1))
        return val if 1.0 <= val <= 5.0 else None
    except ValueError:
        return None


# -- Review count parser ------------------------------------------------------

_REVIEW_RE = re.compile(r"([\d,]+)")

def _parse_review_count(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    m = _REVIEW_RE.search(text)
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None


# -- Delivery parser ----------------------------------------------------------

def _parse_delivery(text: Optional[str]) -> Tuple[Optional[int], Optional[int]]:
    """
    Parses delivery text into (min_days, max_days).
    Examples:
      "Get it by Monday"     -> (1, 2)
      "FREE delivery Sat, 28 Feb" -> (1, 3)
      "1 - 4 Mar"            -> (3, 6)
      "Delivery in 2-5 days" -> (2, 5)
    """
    if not text:
        return None, None

    text_lower = text.lower()

    # "X-Y days" pattern
    m = re.search(r"(\d+)\s*[-\u2013to]+\s*(\d+)\s*days?", text_lower)
    if m:
        return int(m.group(1)), int(m.group(2))

    # "in X days"
    m = re.search(r"in\s+(\d+)\s+days?", text_lower)
    if m:
        d = int(m.group(1))
        return d, d

    # Day-of-week keywords -> rough estimates
    today_keywords = {
        "today": (0, 0), "tonight": (0, 0),
        "tomorrow": (1, 1),
        "monday": (1, 3), "tuesday": (1, 3), "wednesday": (1, 3),
        "thursday": (1, 3), "friday": (1, 3),
        "saturday": (1, 4), "sunday": (1, 4),
    }
    for kw, days in today_keywords.items():
        if kw in text_lower:
            return days

    # "X Mar", "X Feb" style date -> assume within a week
    m = re.search(
        r"(\d{1,2})\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)",
        text_lower,
    )
    if m:
        return 1, 7

    return None, None


# -- Single listing normalizer ------------------------------------------------

def _normalize(listing: RawListing) -> Optional[NormalizedOffer]:
    try:
        cfg           = marketplace_registry.get(listing.platform_key)
        platform_name = cfg.name if cfg else listing.platform_key
        title         = listing.title.strip()

        disc_price = _parse_price(listing.price_text)
        base_price = _parse_price(listing.original_price_text) or disc_price
        rating     = _parse_rating(listing.rating_text)
        reviews    = _parse_review_count(listing.review_count_text)
        del_min, del_max = _parse_delivery(listing.delivery_text)

        effective = round(disc_price, 2) if disc_price is not None else None

        if disc_price is None and listing.price_text:
            logger.warning(
                "Extractor [%s]: could not parse price '%s' for '%s'",
                listing.platform_key, listing.price_text[:40], title[:50],
            )

        return NormalizedOffer(
            platform_key=listing.platform_key,
            platform_name=platform_name,
            listing_url=listing.listing_url or "",
            title=title,
            image_url=getattr(listing, "image_url", None),
            seller_name=listing.seller_text,
            base_price=base_price,
            discounted_price=disc_price,
            effective_price=effective,
            coupon_savings=0.0,
            shipping_fee=0.0,
            delivery_days_min=del_min,
            delivery_days_max=del_max,
            delivery_text=listing.delivery_text,
            seller_rating=rating,
            review_count=reviews,
        )
    except Exception as e:
        logger.error("Extractor [%s]: %s", listing.platform_key, e)
        return None


# -- Public agent entry point -------------------------------------------------

async def run_extractor(state: PipelineState) -> PipelineState:
    if not state.raw_listings:
        state.add_error("Extractor: no raw listings to process")
        return state

    offers = []
    null_price_count = 0
    for listing in state.raw_listings:
        offer = _normalize(listing)
        if offer is None:
            continue
        if offer.effective_price is None:
            null_price_count += 1
        offers.append(offer)

    # Deduplicate by listing_url (if available) OR by (platform_key, title)
    seen = set()
    deduped = []
    for offer in offers:
        # Primary dedup key: exact URL
        if offer.listing_url:
            url_key = offer.listing_url.strip().lower()
            if url_key in seen:
                logger.debug(
                    "Dedup: dropped duplicate URL [%s] %s",
                    offer.platform_key, url_key[:60],
                )
                continue
            seen.add(url_key)
        else:
            # Fallback dedup key: platform + normalized title
            title_key = (
                offer.platform_key + "|" +
                re.sub(r'\s+', ' ', offer.title.lower().strip())
            )
            if title_key in seen:
                logger.debug(
                    "Dedup: dropped duplicate title [%s] %s",
                    offer.platform_key, offer.title[:50],
                )
                continue
            seen.add(title_key)
        deduped.append(offer)

    state.normalized_offers = deduped

    # Warn if all prices are null
    if null_price_count > 0:
        logger.warning(
            "Extractor: %d/%d offers have null price",
            null_price_count, len(offers),
        )

    logger.info(
        "Extractor: %d normalized (%d after dedup, %d with price) from %d raw",
        len(offers), len(deduped),
        len(deduped) - null_price_count, len(state.raw_listings),
    )
    return state
