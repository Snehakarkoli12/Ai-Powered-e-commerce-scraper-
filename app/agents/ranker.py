# app/agents/ranker.py
# -*- coding: utf-8 -*-
"""
Ranker agent: scores, ranks, and assigns badges to matched offers.

LangGraph node: ranker_node(state) → {ranked_results: [...]}
Backward compat: run_ranker(state: PipelineState) → PipelineState

MODE-BASED COMPOSITE SCORING WEIGHTS (master prompt):
  "cheapest":  price 70%, rating 15%, delivery 15%
  "balanced":  price 40%, rating 35%, delivery 25%
  "fastest":   price 15%, rating 15%, delivery 70%
  "reliable":  price 20%, rating 60%, delivery 20%

SCORE NORMALIZATION:
  Price score:    lowest_price / offer_price
  Rating score:   offer_rating / 5.0
  Delivery score: 1 / delivery_days
"""
import logging
from typing import List, Optional
from app.schemas import (
    NormalizedOffer, ScoreBreakdown, PipelineState,
    RankingPreferences, RankingMode,
)

logger = logging.getLogger("ranker")

# Master prompt weights
_WEIGHTS = {
    RankingMode.cheapest: {"price": 0.70, "rating": 0.15, "delivery": 0.15},
    RankingMode.fastest:  {"price": 0.15, "rating": 0.15, "delivery": 0.70},
    RankingMode.reliable: {"price": 0.20, "rating": 0.60, "delivery": 0.20},
    RankingMode.balanced: {"price": 0.40, "rating": 0.35, "delivery": 0.25},
}

_MIN_SCORE_THRESHOLD = 0.05


def _price_score(price: float, lowest_price: float) -> float:
    """Price score: lowest_price / offer_price (lower price = higher score)."""
    if price <= 0:
        return 0.0
    return min(lowest_price / price, 1.0)


def _rating_score(rating: Optional[float]) -> float:
    """Rating score: offer_rating / 5.0."""
    if rating is None or rating <= 0:
        return 0.3  # neutral default when no rating
    return min(rating / 5.0, 1.0)


def _delivery_score(days_max: Optional[int]) -> float:
    """Delivery score: 1 / delivery_days (faster = higher score)."""
    if days_max is None:
        return 0.3  # neutral default when no delivery info
    if days_max == 0:
        return 1.0
    return min(1.0 / days_max, 1.0)


def _rank_offers(offers: List[NormalizedOffer], mode: RankingMode) -> List[NormalizedOffer]:
    """Core ranking logic shared by both run_ranker and ranker_node."""
    weights = _WEIGHTS.get(mode, _WEIGHTS[RankingMode.balanced])

    if not offers:
        return []

    valid_prices = [
        o.effective_price for o in offers
        if o.effective_price is not None
    ]
    if not valid_prices:
        return []

    lowest_price = min(valid_prices)

    scored = []
    for offer in offers:
        if offer.effective_price is None:
            continue

        ps = _price_score(offer.effective_price, lowest_price)
        rs = _rating_score(offer.seller_rating or offer.rating)
        ds = _delivery_score(offer.delivery_days_max)

        composite = (
            weights["price"]    * ps
            + weights["rating"]   * rs
            + weights["delivery"] * ds
        )

        offer.score_breakdown = ScoreBreakdown(
            price_score=round(ps, 3),
            delivery_score=round(ds, 3),
            trust_score=round(rs, 3),
            final_score=round(composite, 3),
        )
        offer.composite_score = round(composite, 3)

        if composite >= _MIN_SCORE_THRESHOLD:
            scored.append(offer)

    scored.sort(key=lambda o: o.composite_score, reverse=True)

    if not scored:
        return []

    # ── Keep up to 5 best offers per site ───────────────────────────────
    site_counts: dict = {}
    MAX_PER_SITE = 5
    deduped: List[NormalizedOffer] = []
    for offer in scored:
        site = offer.platform_key or offer.site
        count = site_counts.get(site, 0)
        if count < MAX_PER_SITE:
            site_counts[site] = count + 1
            deduped.append(offer)
    logger.info("Ranker: deduped %d -> %d (max %d per site)", len(scored), len(deduped), MAX_PER_SITE)
    scored = deduped

    # ── Badge assignment ─────────────────────────────────────────────────
    # "Best Price" → lowest effective_price
    priced = [o for o in scored if o.effective_price is not None]
    best_price_offer = min(priced, key=lambda o: o.effective_price) if priced else None

    # "Fastest Delivery" → shortest delivery_days
    delivery_offers = [o for o in scored if o.delivery_days_max is not None]
    fastest_offer = min(delivery_offers, key=lambda o: o.delivery_days_max) if delivery_offers else None

    # "Most Trusted" → highest rating
    rated_offers = [o for o in scored if (o.seller_rating or o.rating) is not None]
    most_trusted = max(rated_offers, key=lambda o: o.seller_rating or o.rating or 0) if rated_offers else None

    # "Recommended" → highest composite_score
    recommended = scored[0] if scored else None

    for i, offer in enumerate(scored):
        offer.rank = i + 1
        badges: List[str] = []

        if offer is recommended:
            badges.append("Recommended")
        if best_price_offer and offer is best_price_offer:
            badges.append("Best Price")
        if fastest_offer and offer is fastest_offer:
            badges.append("Fastest Delivery")
        if most_trusted and offer is most_trusted:
            badges.append("Most Trusted")

        # One offer can hold multiple badges (deduplicated, order preserved)
        offer.badges = list(dict.fromkeys(badges))

    top_key = scored[0].platform_key if scored else "none"
    top_price = scored[0].effective_price if scored else None
    logger.info(
        "Ranker [%s]: %d ranked, top=%s (score=%.3f, price=%s)",
        mode.value, len(scored), top_key,
        scored[0].composite_score if scored else 0.0,
        f"Rs.{top_price:,.0f}" if top_price else "null",
    )

    return scored


# ── SYNC backward-compat entry point ─────────────────────────────────────────

def run_ranker(state: PipelineState) -> PipelineState:
    prefs: RankingPreferences = (
        getattr(state, "preferences", None) or RankingPreferences()
    )
    mode = prefs.mode_enum()

    ranked = _rank_offers(state.matched_offers, mode)
    state.ranked_offers = ranked
    state.final_offers  = ranked
    return state


# ═══════════════════════════════════════════════════════════════════════════════
# LangGraph node function
# ═══════════════════════════════════════════════════════════════════════════════


def ranker_node(state: dict) -> dict:
    """LangGraph node: Stage 5 — Score, rank, badge, deduplicate offers."""
    matched = state.get("matched_results", [])
    mode_str = state.get("mode", "balanced")

    try:
        mode = RankingMode(mode_str)
    except ValueError:
        mode = RankingMode.balanced

    ranked = _rank_offers(matched, mode)

    logger.info("Ranker node: %d matched → %d ranked", len(matched), len(ranked))

    return {"ranked_results": ranked}
