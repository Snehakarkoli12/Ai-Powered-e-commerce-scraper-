# app/agents/ranker.py
# -*- coding: utf-8 -*-
"""
Ranker agent: scores, ranks, and assigns badges to matched offers.
Handles null price/delivery gracefully.
"""
import logging
from typing import List, Optional
from app.schemas import (
    NormalizedOffer, ScoreBreakdown, PipelineState,
    RankingPreferences, RankingMode,
)

logger = logging.getLogger("ranker")

_WEIGHTS = {
    RankingMode.cheapest: {"price": 0.80, "delivery": 0.10, "trust": 0.10},
    RankingMode.fastest:  {"price": 0.15, "delivery": 0.70, "trust": 0.15},
    RankingMode.reliable: {"price": 0.20, "delivery": 0.20, "trust": 0.60},
    RankingMode.balanced: {"price": 0.40, "delivery": 0.30, "trust": 0.30},
}

_MIN_SCORE_THRESHOLD = 0.05


def _price_score(price: float, min_price: float, max_price: float) -> float:
    if max_price == min_price:
        return 1.0
    return 1.0 - (price - min_price) / (max_price - min_price)


def _delivery_score(days_max: Optional[int]) -> float:
    if days_max is None: return 0.3
    if days_max == 0:    return 1.0
    if days_max <= 1:    return 0.95
    if days_max <= 3:    return 0.80
    if days_max <= 5:    return 0.60
    if days_max <= 7:    return 0.40
    return 0.20


def _trust_score(
    rating:      Optional[float],
    reviews:     Optional[int],
    match_score: float,
) -> float:
    score = 0.5
    if rating is not None:
        score = (rating / 5.0) * 0.6
    if reviews is not None:
        if reviews > 10000:  score += 0.30
        elif reviews > 1000: score += 0.20
        elif reviews > 100:  score += 0.10
    score += match_score * 0.10
    return min(1.0, score)


# -- SYNC -- do NOT add async def here ----------------------------------------
def run_ranker(state: PipelineState) -> PipelineState:
    prefs: RankingPreferences = (
        getattr(state, "preferences", None) or RankingPreferences()
    )
    mode    = prefs.mode_enum()
    weights = _WEIGHTS.get(mode, _WEIGHTS[RankingMode.balanced])

    offers = state.matched_offers
    if not offers:
        state.ranked_offers = []
        state.final_offers  = []
        return state

    valid_prices = [
        o.effective_price for o in offers
        if o.effective_price is not None
    ]
    has_any_prices = bool(valid_prices)

    if valid_prices:
        min_p, max_p = min(valid_prices), max(valid_prices)
    else:
        min_p = max_p = 0.0

    # Track how many offers have delivery data
    has_any_delivery = any(o.delivery_days_max is not None for o in offers)

    scored = []
    for offer in offers:
        # Price scoring: only meaningful when we have actual prices
        if offer.effective_price is not None and has_any_prices:
            ps = _price_score(offer.effective_price, min_p, max_p)
        else:
            ps = 0.5  # neutral when no price data

        ds = _delivery_score(offer.delivery_days_max)
        ts = _trust_score(offer.seller_rating, offer.review_count, offer.match_score)

        final = (
            weights["price"]    * ps
            + weights["delivery"] * ds
            + weights["trust"]    * ts
        )

        offer.score_breakdown = ScoreBreakdown(
            price_score=round(ps, 3),
            delivery_score=round(ds, 3),
            trust_score=round(ts, 3),
            final_score=round(final, 3),
        )

        if final >= _MIN_SCORE_THRESHOLD:
            scored.append(offer)

    scored.sort(key=lambda o: o.score_breakdown.final_score, reverse=True)

    if not scored:
        state.ranked_offers = []
        state.final_offers  = []
        return state

    # Badge assignment -- ONLY assign when data is meaningful
    # Best Price: only when at least 2 offers have prices and winner is actually cheapest
    best_price_offer = None
    if has_any_prices:
        priced_offers = [o for o in scored if o.effective_price is not None]
        if len(priced_offers) >= 1:
            best_price_offer = min(priced_offers, key=lambda o: o.effective_price)

    # Fastest Delivery: only when at least 1 offer has delivery data
    fastest_offer = None
    if has_any_delivery:
        delivery_offers = [o for o in scored if o.delivery_days_max is not None]
        if delivery_offers:
            fastest_offer = min(delivery_offers, key=lambda o: o.delivery_days_max)

    # Most Trusted: only assign when there's meaningful trust score variation
    most_trusted = None
    trust_scores = [o.score_breakdown.trust_score for o in scored]
    if max(trust_scores) - min(trust_scores) > 0.05:
        most_trusted = max(scored, key=lambda o: o.score_breakdown.trust_score)

    for i, offer in enumerate(scored):
        offer.rank = i + 1
        badges: List[str] = []

        if i == 0:
            badges.append("Recommended")

        if best_price_offer and offer is best_price_offer:
            badges.append("Best Price")

        if fastest_offer and offer is fastest_offer:
            badges.append("Fastest Delivery")

        if most_trusted and offer is most_trusted:
            badges.append("Most Trusted")

        offer.badges = list(dict.fromkeys(badges))  # deduplicate, preserve order

    top_key = scored[0].platform_key if scored else "none"
    top_price = scored[0].effective_price if scored else None
    logger.info(
        "Ranker [%s]: %d ranked, top=%s (score=%.3f, price=%s)",
        mode.value,
        len(scored),
        top_key,
        scored[0].score_breakdown.final_score if scored else 0.0,
        f"Rs.{top_price:,.0f}" if top_price else "null",
    )

    state.ranked_offers = scored
    state.final_offers  = scored

    return state
