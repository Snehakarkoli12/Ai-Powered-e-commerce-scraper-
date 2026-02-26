from __future__ import annotations
import asyncio
import re
from typing import Optional, Tuple, List

from app.schemas import RawListing, NormalizedOffer
from app.marketplaces.registry import marketplace_registry
from app.agents import PipelineState
from app.utils.logger import get_logger

logger = get_logger(__name__)

_DEL_KW   = ['day','deliver','dispatch','ship','arriv','today','tomorrow','hour','express']
_LOC_PAT  = re.compile(r'\b\d{6}\b')
_JUNK_TTL = ["add to compare","coming soon","sponsored","new arrival","best seller"]


def _clean_title(raw: Optional[str]) -> Optional[str]:
    if not raw: return None
    for line in [l.strip() for l in raw.split('\n') if l.strip()]:
        if not any(line.lower().startswith(j) for j in _JUNK_TTL) and len(line) > 5:
            return line
    return None


def _parse_price(text: Optional[str]) -> Optional[float]:
    if not text: return None
    c = re.sub(r'[₹$£€]','', text)
    c = re.sub(r'\b(Rs\.?|INR)\b','', c, flags=re.IGNORECASE)
    c = c.replace(',','').strip()
    m = re.search(r'\d+(?:\.\d+)?', c)
    if m:
        try:
            v = float(m.group(0))
            return v if 0 < v < 10_000_000 else None
        except ValueError: pass
    return None


def _parse_rating(text: Optional[str]) -> Optional[float]:
    if not text: return None
    m = re.search(r'(\d+\.?\d*)\s*(?:out\s*of\s*5|stars?|★)?', text, re.IGNORECASE)
    if m:
        try:
            v = float(m.group(1))
            return v if 0.0 <= v <= 5.0 else None
        except ValueError: pass
    return None


def _parse_review_count(text: Optional[str]) -> Optional[int]:
    if not text: return None
    t = text.replace(',','')
    k = re.search(r'(\d+\.?\d*)\s*[kK]', t)
    if k: return int(float(k.group(1)) * 1000)
    m = re.search(r'\d+', t)
    return int(m.group(0)) if m else None


def _parse_delivery(text: Optional[str]) -> Tuple[Optional[int], Optional[int]]:
    if not text: return None, None
    if _LOC_PAT.search(text): return None, None
    if not any(k in text.lower() for k in _DEL_KW): return None, None
    t = text.lower()
    if 'today' in t or 'same day' in t: return 0, 0
    if 'tomorrow' in t: return 1, 1
    r = re.search(r'(\d+)\s*[-–to]+\s*(\d+)\s*days?', t)
    if r: return int(r.group(1)), int(r.group(2))
    s = re.search(r'(?:in|within|by|under)\s*(\d+)\s*days?', t)
    if s: d = int(s.group(1)); return d, d
    b = re.search(r'(\d+)\s*days?', t)
    if b: d = int(b.group(1)); return d, d
    return None, None


def _normalize(listing: RawListing) -> NormalizedOffer:
    cfg           = marketplace_registry.get(listing.platform_key)
    platform_name = cfg.name if cfg else listing.platform_key
    title         = _clean_title(listing.title) or listing.title or ""
    disc_price    = _parse_price(listing.price_text)
    base_price    = _parse_price(listing.original_price_text) or disc_price
    rating        = _parse_rating(listing.rating_text)
    reviews       = _parse_review_count(listing.review_count_text)
    del_min, del_max = _parse_delivery(listing.delivery_text)
    effective     = round(disc_price, 2) if disc_price is not None else None

    return NormalizedOffer(
        platform_key=listing.platform_key, platform_name=platform_name,
        listing_url=listing.listing_url or "", title=title,
        seller_name=listing.seller_text,
        base_price=base_price, discounted_price=disc_price,
        effective_price=effective,
        delivery_days_min=del_min, delivery_days_max=del_max,
        delivery_text=listing.delivery_text,
        seller_rating=rating, review_count=reviews,
    )


async def _llm_enrich(listing: RawListing) -> RawListing:
    """Enrich missing fields via LLM — only called when price is null."""
    try:
        from app.agents.llm_extractor import llm_extract_card
        parts     = [listing.title or "", listing.price_text or "", listing.delivery_text or ""]
        card_text = " | ".join(p for p in parts if p)
        result    = await llm_extract_card(card_text, listing.platform_key)
        if not result:
            return listing
        if not listing.price_text and result.get("price"):
            listing.price_text = str(result["price"])
        if not listing.original_price_text and result.get("original_price"):
            listing.original_price_text = str(result["original_price"])
        if not listing.delivery_text and result.get("delivery_days_max") is not None:
            listing.delivery_text = f"in {result['delivery_days_max']} days"
        if not listing.rating_text and result.get("seller_rating"):
            listing.rating_text = str(result["seller_rating"])
        if not listing.review_count_text and result.get("review_count"):
            listing.review_count_text = str(result["review_count"])
        if result.get("title") and len(result["title"]) > len(listing.title or ""):
            listing.title = result["title"]
    except Exception as e:
        logger.error(f"LLM enrich [{listing.platform_key}]: {e}")
    return listing


async def run_extractor(state: PipelineState) -> PipelineState:
    """Stage 3 — Normalize raw listings; LLM enriches cards with missing price."""
    if not state.raw_listings:
        logger.warning("Extractor: no raw_listings to process")
        return state

    # Separate: cards missing price get LLM enrichment
    needs_llm = [l for l in state.raw_listings if not l.price_text]
    has_price = [l for l in state.raw_listings if l.price_text]

    if needs_llm:
        logger.info(f"Extractor: {len(needs_llm)} cards missing price → LLM enrichment")
        enriched     = await asyncio.gather(*[_llm_enrich(l) for l in needs_llm])
        all_listings = has_price + list(enriched)
    else:
        all_listings = state.raw_listings

    normalized, failed = [], 0
    for listing in all_listings:
        try:
            offer = _normalize(listing)
            normalized.append(offer)
        except Exception as e:
            state.add_error(f"Extractor [{listing.platform_key}]: {e}")
            failed += 1

    state.normalized_offers = normalized
    logger.info(f"Extractor: {len(normalized)} normalized, {failed} failed")
    return state
