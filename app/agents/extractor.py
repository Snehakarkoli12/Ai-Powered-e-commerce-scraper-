# -*- coding: utf-8 -*-
"""
Extractor agent: RawListing -> NormalizedOffer
Parses price, delivery, rating from text fields.

LangGraph node: extractor_node(state) → {cleaned_results: [...]}
Backward-compat: run_extractor(state) → PipelineState

5 transformations in EXACT order per master prompt:
  1. PRICE NORMALIZATION (Regex)
  2. RATING NORMALIZATION (Regex)
  3. DELIVERY NORMALIZATION (Regex)
  4. URL CLEANING (Regex)
  5. DEDUPLICATION
"""
from __future__ import annotations
import re
from typing import Optional, Tuple
from urllib.parse import urlparse, urlencode, parse_qs, quote_plus

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


# ── URL cleaning per master prompt ───────────────────────────────────────────

# Tracking query params we always want to strip (analytics noise)
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "ref", "ref_", "tag", "campaign", "crid", "sprefix", "qid", "sr",
    "linkcode", "camp", "creative", "creativesin", "th", "psc",
    "s", "otracker", "searchclick", "marketplace", "store", "srno",
    "lid", "ssid", "qH", "affid", "dclid", "gclid", "fbclid",
    "affiliate_id", "offer_id", "_referer",
}


def _clean_url_for_site(url: str, site_key: str) -> str:
    """Clean URLs per master prompt:
    Amazon: extract /dp/ASIN only → full amazon.in URL
    Flipkart: base URL + path (keeps pid if present)
    Others: keep full URL, only strip tracking params
    """
    if not url:
        return ""

    url = url.strip()

    # If URL is a bare path, prepend the base URL from marketplace config
    if url.startswith("/"):
        cfg = marketplace_registry.get(site_key)
        base = cfg.base_url.rstrip("/") if cfg else ""
        if base:
            url = base + url
        else:
            return ""

    # Must start with http now
    if not url.startswith("http"):
        # Try prepending base URL as last resort
        cfg = marketplace_registry.get(site_key)
        if cfg and cfg.base_url:
            url = cfg.base_url.rstrip("/") + "/" + url.lstrip("/")
        else:
            return ""

    try:
        parsed = urlparse(url)

        if site_key == "amazon" or "amazon" in parsed.netloc:
            # Extract /dp/ASIN pattern
            m = re.search(r'/dp/([A-Z0-9]{10})', url)
            if m:
                return f"https://www.amazon.in/dp/{m.group(1)}"
            return url.split("/ref=")[0]  # Still valid, just strip ref param

        if site_key == "flipkart" or "flipkart" in parsed.netloc:
            # Keep base URL + path + pid param if present
            base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            qs = parse_qs(parsed.query)
            if "pid" in qs:
                return f"{base}?pid={qs['pid'][0]}"
            return base

        # For ALL other sites: keep the full URL but strip tracking params
        if parsed.query:
            qs = parse_qs(parsed.query)
            cleaned_qs = {k: v[0] for k, v in qs.items()
                          if k.lower() not in _TRACKING_PARAMS}
            if cleaned_qs:
                clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{urlencode(cleaned_qs)}"
            else:
                clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        else:
            clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

        return clean if parsed.netloc else url

    except Exception:
        return url


def _build_fallback_url(title: str, site_key: str) -> str:
    """Generate a search URL for the product on the given marketplace.
    Used when no direct product URL was extracted.
    """
    from urllib.parse import quote_plus
    cfg = marketplace_registry.get(site_key)
    if not cfg or not cfg.search_url_pattern:
        return ""
    try:
        # Use first 60 chars of title as search query (avoid overly long URLs)
        search_term = title.strip()[:60].strip()
        return cfg.search_url_pattern.format(query=quote_plus(search_term))
    except Exception:
        return ""


# ═══════════════════════════════════════════════════════════════════════════════
# LangGraph node function
# ═══════════════════════════════════════════════════════════════════════════════


def extractor_node(state: dict) -> dict:
    """LangGraph node: Stage 3 — Normalize raw scraper results.

    5 transformations in EXACT order:
      1. PRICE NORMALIZATION
      2. RATING NORMALIZATION
      3. DELIVERY NORMALIZATION
      4. URL CLEANING
      5. DEDUPLICATION

    Rule: if price unparseable → skip listing entirely.
    Final: sorted by effective_price ascending.
    """
    raw_results = state.get("raw_results", [])

    if not raw_results:
        logger.warning("Extractor node: no raw results to process")
        return {"cleaned_results": []}

    offers = []
    for listing in raw_results:
        offer = _normalize(listing)
        if offer is None:
            continue
        # Master prompt: if price unparseable → skip listing entirely
        if offer.effective_price is None:
            continue

        # Set master prompt alias fields
        offer.raw_price = listing.price_text if hasattr(listing, 'price_text') else None
        offer.site = offer.platform_key
        offer.url = offer.listing_url
        offer.rating = offer.seller_rating
        offer.delivery = offer.delivery_text

        # URL cleaning per site
        offer.listing_url = _clean_url_for_site(offer.listing_url, offer.platform_key)
        # Fallback: if no valid product URL, generate a search URL so frontend always has a link
        if not offer.listing_url:
            offer.listing_url = _build_fallback_url(offer.title, offer.platform_key)
            if offer.listing_url:
                logger.info(
                    "Extractor [%s]: no product URL for '%s' → fallback search URL",
                    offer.platform_key, offer.title[:50],
                )
        offer.url = offer.listing_url

        offers.append(offer)

    # Deduplication: fingerprint = site + str(effective_price) + title[:40].lower()
    seen = set()
    deduped = []
    for offer in offers:
        fp = f"{offer.platform_key}_{offer.effective_price}_{offer.title[:40].lower()}"
        if fp in seen:
            logger.debug(
                "Extractor node dedup: dropped [%s] '%s'",
                offer.platform_key, offer.title[:50],
            )
            continue
        seen.add(fp)
        deduped.append(offer)

    # Sort by effective_price ascending
    deduped.sort(key=lambda o: o.effective_price if o.effective_price is not None else float('inf'))

    logger.info(
        "Extractor node: %d raw → %d normalized → %d deduped (sorted by price)",
        len(raw_results), len(offers), len(deduped),
    )

    return {"cleaned_results": deduped}
