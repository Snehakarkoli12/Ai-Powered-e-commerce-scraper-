# -*- coding: utf-8 -*-
"""
Matcher agent: scores each NormalizedOffer against the NormalizedProduct target.
Hard-rejects wrong variants and model numbers.
Uses query-keyword overlap as the primary relevance gate.
Scores ALL offers -- not just the first per platform.
"""
from __future__ import annotations
import re
from typing import Optional, Set

from app.schemas import PipelineState, NormalizedOffer, NormalizedProduct
from app.utils.logger import get_logger

logger = get_logger(__name__)


# -- Variant rejection tokens -------------------------------------------------
# If target does NOT contain these tokens but title does -> hard reject (score=0)
_VARIANT_TOKENS = {
    "fe", "ultra", "plus", "lite", "mini",
    "s23", "s22", "s21", "s20", "s25", "s10",
    "a54", "a55", "a35", "a15", "a05",
    "note", "fold", "flip",
}

# Category keywords that indicate an accessory or wrong product type
_REJECT_KEYWORDS = [
    "television", " tv ", "monitor", "laptop", "tablet",
    "smartwatch", "earphone", "earbud", "headphone",
    "charger", "cable", "case", "cover",
    "screen guard", "power bank", "speaker",
    "trimmer", "shaver", "pain", "gel", "cream",
    "watch band", "strap",
]

# Stopwords excluded from query-keyword matching (too generic)
_STOPWORDS: Set[str] = {
    "the", "a", "an", "and", "or", "for", "in", "on", "at", "to", "of",
    "with", "by", "is", "it", "its", "this", "that", "from", "up",
    "new", "best", "buy", "price", "online", "india", "shop", "store",
    "rs", "inr", "rupees", "product", "mobile", "phone", "smartphone",
}


def _tokenize(text: str) -> set:
    """Lowercase alphanumeric tokens from any string."""
    if not text:
        return set()
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _meaningful_query_tokens(query: str) -> set:
    """Extract meaningful (non-stopword) tokens from the search query."""
    tokens = _tokenize(query)
    return tokens - _STOPWORDS


def _extract_storage(text: str) -> Optional[str]:
    m = re.search(r"(\d+)\s*gb", text.lower())
    return m.group(1) + "gb" if m else None


def _extract_model_numbers(text: str) -> set:
    """Extract all numeric model identifiers from text.
    E.g. 'JBL Tune 770NC' -> {'770'}
         'Galaxy S24 Ultra' -> {'24'}
         'iPhone 15 Pro' -> {'15'}
    """
    if not text:
        return set()
    # Find numbers that are part of model names (not storage like 128GB)
    # Match digits that are NOT followed by GB/TB
    tokens = re.findall(r'\b(\d{2,4})\b(?!\s*(?:gb|tb|mm|mp|mah|w|wh))', text.lower())
    return set(tokens)


def _compute_match_score(
    offer:  NormalizedOffer,
    target: NormalizedProduct,
) -> float:
    """
    Returns 0.0-1.0 match score.
    0.0 = hard reject (wrong product / wrong variant / no query overlap).
    """
    title_lower  = offer.title.lower()
    title_tokens = _tokenize(offer.title)

    # Read target attributes
    attrs = target.attributes
    target_brand   = (attrs.brand   or "").lower().strip()
    target_model   = (attrs.model   or "").lower().strip()
    target_storage = (attrs.storage or "").lower().strip()
    target_query   = (target.search_query or "").lower().strip()
    raw_query      = (attrs.raw_query or "").lower().strip()

    target_model_tokens = _tokenize(target_model)
    target_query_tokens = _tokenize(target_query)

    # Combined target tokens for variant checking
    all_target_tokens = target_model_tokens | target_query_tokens

    # ── PRIMARY GATE: query-keyword overlap ────────────────────────────────
    # The offer title MUST contain at least some meaningful words from the
    # user's original query.  Without this, completely unrelated products
    # (trending items, suggested products) sneak through.
    meaningful_q = _meaningful_query_tokens(raw_query or target_query)
    if meaningful_q:
        overlap = meaningful_q & title_tokens
        overlap_ratio = len(overlap) / len(meaningful_q)
        # Require >= 40% of meaningful query tokens in the title
        if overlap_ratio < 0.4:
            logger.debug(
                "Matcher: query-keyword reject '%s' — overlap %.0f%% (%s ∩ %s)",
                offer.title[:60], overlap_ratio * 100, overlap, meaningful_q,
            )
            return 0.0

    # -- Hard reject: wrong product category / accessory -----------------------
    # Only apply category rejection if the target query is NOT for that category
    target_combined = (target_brand + " " + target_model + " " + target_query).lower()
    for kw in _REJECT_KEYWORDS:
        kw_clean = kw.strip()
        if kw_clean in title_lower and kw_clean not in target_combined:
            logger.debug("Matcher: category reject '%s' (keyword: '%s')", offer.title[:50], kw_clean)
            return 0.0

    # -- Hard reject: wrong variant --------------------------------------------
    for vtoken in _VARIANT_TOKENS:
        target_has = vtoken in all_target_tokens
        title_has  = vtoken in title_tokens

        if title_has and not target_has:
            logger.debug(
                "Matcher: variant reject '%s' -- token '%s' not in target",
                offer.title[:50], vtoken,
            )
            return 0.0

    # -- Hard reject: wrong storage --------------------------------------------
    if target_storage:
        offer_storage = _extract_storage(offer.title)
        if offer_storage and offer_storage != target_storage.replace(" ", ""):
            logger.debug(
                "Matcher: storage reject '%s' -- %s != %s",
                offer.title[:50], offer_storage, target_storage,
            )
            return 0.0

    # -- Hard reject: wrong model number ---------------------------------------
    # E.g. JBL Tune 770NC vs JBL Tune 750BT -> different model numbers
    target_model_nums = _extract_model_numbers(target_model)
    if target_model_nums:
        offer_model_nums = _extract_model_numbers(offer.title)
        if offer_model_nums:
            # Check if the model numbers match
            # If target has "770" and offer has "750", that's a mismatch
            if not target_model_nums & offer_model_nums:
                logger.debug(
                    "Matcher: model number reject '%s' -- nums %s vs target %s",
                    offer.title[:50], offer_model_nums, target_model_nums,
                )
                return 0.0

    # -- Positive scoring ------------------------------------------------------
    score     = 0.0
    max_score = 0.0

    # Brand match (0.20)
    if target_brand:
        max_score += 0.20
        if target_brand in title_lower:
            score += 0.20

    # Model token overlap (0.40)
    if target_model_tokens:
        max_score += 0.40
        matched    = target_model_tokens & title_tokens
        score     += 0.40 * (len(matched) / len(target_model_tokens))

    # Storage match (0.15)
    if target_storage:
        max_score += 0.15
        if target_storage.replace(" ", "") in title_lower.replace(" ", ""):
            score += 0.15

    # Query-keyword overlap bonus (0.25) — always available
    if meaningful_q:
        max_score += 0.25
        overlap = meaningful_q & title_tokens
        score  += 0.25 * (len(overlap) / len(meaningful_q))

    if max_score == 0.0:
        # Absolute fallback — no target info at all.  Use a very low score
        # so it only passes if the min_match_score threshold allows it.
        return 0.15

    return round(score / max_score, 3)


# -- Public agent entry point -------------------------------------------------

async def run_matcher(state: PipelineState) -> PipelineState:
    if not state.normalized_offers:
        logger.warning("Matcher: nothing to process")
        return state

    target     = state.normalized_product
    # Default min_match_score is 0.4 — filters out clearly irrelevant items
    min_score  = 0.4
    prefs      = getattr(state, "preferences", None)
    if prefs and hasattr(prefs, "min_match_score") and prefs.min_match_score > 0:
        min_score = prefs.min_match_score

    matched = []
    rejected_count = 0

    for offer in state.normalized_offers:
        score = _compute_match_score(offer, target)
        offer.match_score = score

        # Reject offers with no price — can't compare them
        if offer.effective_price is None:
            rejected_count += 1
            logger.info(
                "Matcher: rejected '%s' [%s] — no price",
                offer.title[:50], offer.platform_key,
            )
            continue

        if score > 0.0 and score >= min_score:
            matched.append(offer)
        else:
            rejected_count += 1
            logger.info(
                "Matcher: rejected '%s' [%s] score=%.3f (min=%.2f)",
                offer.title[:50], offer.platform_key, score, min_score,
            )

    logger.info(
        "Matcher: %d -> %d offers (rejected %d)",
        len(state.normalized_offers),
        len(matched),
        rejected_count,
    )
    state.matched_offers = matched
    return state
