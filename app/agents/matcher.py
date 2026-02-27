# -*- coding: utf-8 -*-
"""
Matcher agent: scores each NormalizedOffer against the NormalizedProduct target.

LangGraph node: matcher_node(state) → {matched_results, match_attempts}
Conditional edge: should_retry_or_continue(state) → "planner"/"ranker"/"explainer"
Backward compat: run_matcher(state: PipelineState) → PipelineState

6 HARD REJECTION GATES per master prompt:
  Gate 1 → Accessory keywords in title
  Gate 2 → Wrong brand
  Gate 3 → Model tokens missing
  Gate 4 → Wrong variant
  Gate 5 → Storage mismatch
  Gate 6 → Wrong generation

WEIGHTED SCORING (only if all 6 gates passed):
  Brand match:          +0.20
  Model token overlap:  +0.40
  Storage match:        +0.20
  Query token coverage: +0.15
  Title quality bonus:  +0.05
"""
from __future__ import annotations
import re
from typing import Optional, Set

from app.schemas import PipelineState, NormalizedOffer, NormalizedProduct
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ── Gate 1: Accessory keywords ───────────────────────────────────────────────

_ACCESSORY_KEYWORDS = [
    "case", "cover", "charger", "cable", "strap",
    "screen guard", "protector", "earphone", "adapter",
    "stand", "holder", "band", "skin", "pouch",
]


# ── Gate 2: Known brands for wrong-brand rejection ──────────────────────────

_KNOWN_BRANDS = {
    "apple", "oneplus", "xiaomi", "realme",
    "oppo", "vivo", "nokia", "motorola", "google",
    "samsung", "redmi", "poco", "asus", "lenovo",
    "hp", "dell", "acer", "sony", "lg",
}


# ── Gate 4: Variant tokens ──────────────────────────────────────────────────

_VARIANT_TOKENS = {
    "fe", "plus", "ultra", "lite", "mini",
    "pro", "max", "edge", "neo", "a",
}


# ── Stopwords for query matching ─────────────────────────────────────────────

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


def _extract_storage(text: str) -> Optional[str]:
    m = re.search(r"(\d+)\s*gb", text.lower())
    return m.group(1) + "gb" if m else None


def _extract_series_number(text: str) -> Optional[str]:
    """Extract numeric series e.g. S24 → '24', iPhone 15 → '15'."""
    m = re.search(r'[a-z](\d{1,3})\b', text.lower())
    return m.group(1) if m else None


def _compute_match_score(
    offer:  NormalizedOffer,
    target: NormalizedProduct,
) -> float:
    """
    Returns 0.0-1.0 match score.
    0.0 = hard reject (failed one of 6 gates).
    Positive score = weighted combination of matching factors.
    """
    title_lower  = offer.title.lower()
    title_tokens = _tokenize(offer.title)

    # Read target attributes
    attrs = target.attributes
    target_brand   = (attrs.brand   or target.brand or "").lower().strip()
    target_model   = (attrs.model   or target.model or "").lower().strip()
    target_storage = (attrs.storage or target.storage or "").lower().strip()
    target_query   = (target.search_query or "").lower().strip()
    raw_query      = (attrs.raw_query or target.raw_query or "").lower().strip()

    target_model_tokens = _tokenize(target_model)
    target_query_tokens = _tokenize(target_query) - _STOPWORDS

    # ── GATE 1: Accessory keywords ───────────────────────────────────────
    for kw in _ACCESSORY_KEYWORDS:
        if kw in title_lower:
            logger.debug("Matcher: Gate 1 reject '%s' (accessory: '%s')", offer.title[:50], kw)
            return 0.0

    # ── GATE 2: Wrong brand ──────────────────────────────────────────────
    # Only reject if a DIFFERENT known brand is present in the title
    if target_brand:
        for known in _KNOWN_BRANDS:
            if known != target_brand and known in title_tokens:
                logger.debug("Matcher: Gate 2 reject '%s' (wrong brand: '%s')", offer.title[:50], known)
                return 0.0

    # ── GATE 3: Model tokens missing ─────────────────────────────────────
    # All target_model_tokens must appear in title_tokens
    # Exception: allow 1 miss if len(target_model_tokens) >= 3
    if target_model_tokens:
        missing = target_model_tokens - title_tokens
        allowed_misses = 1 if len(target_model_tokens) >= 3 else 0
        if len(missing) > allowed_misses:
            logger.debug(
                "Matcher: Gate 3 reject '%s' (model tokens missing: %s)",
                offer.title[:50], missing,
            )
            return 0.0

    # ── GATE 4: Wrong variant ────────────────────────────────────────────
    # Combined target tokens for variant checking
    all_target_tokens = target_model_tokens | _tokenize(raw_query or target_query)
    target_has_variant = None
    title_has_variant = None
    for v in _VARIANT_TOKENS:
        if v in all_target_tokens:
            target_has_variant = v
        if v in title_tokens:
            title_has_variant = v

    # If target has NO variant → title must have NO variant
    if target_has_variant is None and title_has_variant is not None:
        logger.debug(
            "Matcher: Gate 4 reject '%s' (has variant '%s' but target has none)",
            offer.title[:50], title_has_variant,
        )
        return 0.0

    # If target HAS variant → title MUST have same variant
    if target_has_variant is not None and title_has_variant != target_has_variant:
        logger.debug(
            "Matcher: Gate 4 reject '%s' (variant mismatch: %s vs %s)",
            offer.title[:50], title_has_variant, target_has_variant,
        )
        return 0.0

    # ── GATE 5: Storage mismatch ─────────────────────────────────────────
    # Only check if target.storage is not empty
    if target_storage:
        offer_storage = _extract_storage(offer.title)
        if offer_storage and offer_storage != target_storage.replace(" ", ""):
            logger.debug(
                "Matcher: Gate 5 reject '%s' (storage: %s != %s)",
                offer.title[:50], offer_storage, target_storage,
            )
            return 0.0

    # ── GATE 6: Wrong generation ─────────────────────────────────────────
    # Extract numeric series from target.model; title must contain same
    target_series = _extract_series_number(target_model)
    if target_series:
        offer_series = _extract_series_number(offer.title)
        if offer_series and offer_series != target_series:
            logger.debug(
                "Matcher: Gate 6 reject '%s' (generation: %s != %s)",
                offer.title[:50], offer_series, target_series,
            )
            return 0.0

    # ── WEIGHTED SCORING (all 6 gates passed) ────────────────────────────
    score = 0.0

    # Brand match: +0.20
    if target_brand:
        if target_brand in title_lower:
            score += 0.20
    else:
        score += 0.20   # full score if no brand constraint

    # Model token overlap: +0.40 × (overlap / total)
    if target_model_tokens:
        matched = target_model_tokens & title_tokens
        score += 0.40 * (len(matched) / len(target_model_tokens))
    else:
        score += 0.40   # full score if no model constraint

    # Storage match: +0.20
    if target_storage:
        if target_storage.replace(" ", "") in title_lower.replace(" ", ""):
            score += 0.20
    else:
        score += 0.20   # full 0.20 if no storage constraint

    # Query token coverage: +0.15 × (overlap / total)
    if target_query_tokens:
        overlap = target_query_tokens & title_tokens
        score += 0.15 * (len(overlap) / len(target_query_tokens))
    else:
        score += 0.15

    # Title quality bonus: +0.05 if word count between 4–20
    word_count = len(offer.title.split())
    if 4 <= word_count <= 20:
        score += 0.05

    return round(min(score, 1.0), 3)


# ── Public agent entry point (backward-compat) ──────────────────────────────

async def run_matcher(state: PipelineState) -> PipelineState:
    if not state.normalized_offers:
        logger.warning("Matcher: nothing to process")
        return state

    target     = state.normalized_product
    min_score  = 0.4
    prefs      = getattr(state, "preferences", None)
    if prefs and hasattr(prefs, "min_match_score") and prefs.min_match_score > 0:
        min_score = prefs.min_match_score

    matched = []
    rejected_count = 0

    for offer in state.normalized_offers:
        score = _compute_match_score(offer, target)
        offer.match_score = score

        if offer.effective_price is None:
            rejected_count += 1
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
        len(state.normalized_offers), len(matched), rejected_count,
    )
    state.matched_offers = matched
    return state


# ═══════════════════════════════════════════════════════════════════════════════
# LangGraph node function
# ═══════════════════════════════════════════════════════════════════════════════


def matcher_node(state: dict) -> dict:
    """LangGraph node: Stage 4 — Score and filter offers.

    Entry: run_matcher(state) → {matched_results, match_attempts}
    Increments match_attempts each run (Matcher owns this counter).
    """
    cleaned = state.get("cleaned_results", [])
    normalized_product = state.get("normalized_product")
    match_attempts = state.get("match_attempts", 0)

    if not cleaned or not normalized_product:
        logger.warning("Matcher node: empty cleaned_results or no target")
        return {
            "matched_results": [],
            "match_attempts": match_attempts + 1,
        }

    # Score threshold
    min_score = 0.4

    matched = []
    rejected = 0

    for offer in cleaned:
        # Gate A: offer.effective_price is None → reject
        if offer.effective_price is None:
            rejected += 1
            continue

        score = _compute_match_score(offer, normalized_product)
        offer.match_score = score

        # Gate B: score == 0.0 OR score < min_score → reject
        if score == 0.0 or score < min_score:
            rejected += 1
            logger.info(
                "Matcher node: rejected '%s' [%s] score=%.3f",
                offer.title[:50], offer.platform_key, score,
            )
            continue

        matched.append(offer)

    new_attempts = match_attempts + 1
    logger.info(
        "Matcher node: %d → %d matched, %d rejected (attempt #%d)",
        len(cleaned), len(matched), rejected, new_attempts,
    )

    return {
        "matched_results": matched,
        "match_attempts": new_attempts,
    }


def should_retry_or_continue(state: dict) -> str:
    """LangGraph conditional edge after matcher.

    matched empty AND attempts < 2  → "planner" (loop back for retry)
    matched empty AND attempts >= 2 → "explainer" (graceful fail)
    matched not empty               → "ranker"
    """
    matched  = state.get("matched_results", [])
    attempts = state.get("match_attempts", 0)

    if matched:
        logger.info("Matcher → ranker (%d matched offers)", len(matched))
        return "ranker"
    elif attempts < 2:
        logger.info("Matcher → planner (retry, attempts=%d)", attempts)
        return "planner"
    else:
        logger.info("Matcher → explainer (graceful fail, attempts=%d)", attempts)
        return "explainer"
