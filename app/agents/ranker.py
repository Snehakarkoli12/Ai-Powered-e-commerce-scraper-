from __future__ import annotations
import math
from typing import List, Dict

from app.schemas import NormalizedOffer, PreferenceMode, ScoreBreakdown
from app.agents import PipelineState
from app.utils.logger import get_logger

logger = get_logger(__name__)

_WEIGHTS: Dict[PreferenceMode, Dict[str, float]] = {
    PreferenceMode.CHEAPEST: {"price": 0.70, "delivery": 0.15, "trust": 0.15},
    PreferenceMode.FASTEST:  {"price": 0.20, "delivery": 0.60, "trust": 0.20},
    PreferenceMode.RELIABLE: {"price": 0.20, "delivery": 0.20, "trust": 0.60},
    PreferenceMode.BALANCED: {"price": 0.40, "delivery": 0.30, "trust": 0.30},
}


def _price_score(o: NormalizedOffer, all_: List[NormalizedOffer]) -> float:
    prices = [x.effective_price for x in all_ if x.effective_price]
    if not prices or o.effective_price is None: return 0.5
    lo, hi = min(prices), max(prices)
    return 1.0 if hi == lo else round(1 - (o.effective_price - lo) / (hi - lo), 3)


def _delivery_score(o: NormalizedOffer, all_: List[NormalizedOffer]) -> float:
    days = [x.delivery_days_max for x in all_ if x.delivery_days_max is not None]
    if not days or o.delivery_days_max is None: return 0.5
    lo, hi = min(days), max(days)
    return 1.0 if hi == lo else round(1 - (o.delivery_days_max - lo) / (hi - lo), 3)


def _trust_score(o: NormalizedOffer) -> float:
    from app.marketplaces.registry import marketplace_registry
    cfg = marketplace_registry.get(o.platform_key)
    pt  = cfg.trust_score_base if cfg else 0.70
    rat = (o.seller_rating / 5.0) if o.seller_rating else 0.6
    rev = min(math.log10(o.review_count + 1) / 3.0, 1.0) if o.review_count else 0.4
    return round(pt * 0.4 + rat * 0.4 + rev * 0.2, 3)


def _assign_badges(ranked: List[NormalizedOffer]):
    if not ranked: return
    ranked[0].recommendation_note = "🏆 Top Pick"

    def _add(offer, badge):
        c = offer.recommendation_note or ""
        if badge not in c:
            offer.recommendation_note = (c + " " + badge).strip()

    priced   = [o for o in ranked if o.effective_price]
    delivered = [o for o in ranked if o.delivery_days_max is not None]
    trusted  = [o for o in ranked if o.score_breakdown.trust_score > 0]

    if priced:    _add(min(priced,    key=lambda x: x.effective_price),             "💰 Lowest Price")
    if delivered: _add(min(delivered, key=lambda x: x.delivery_days_max),           "⚡ Fastest")
    if trusted:   _add(max(trusted,   key=lambda x: x.score_breakdown.trust_score), "⭐ Most Trusted")


def _template_explanation(ranked: List[NormalizedOffer], mode: PreferenceMode) -> str:
    if not ranked:
        return "No matching offers found."
    top   = ranked[0]
    price = f"₹{top.effective_price:,.0f}" if top.effective_price else "N/A"
    del_  = (f"{top.delivery_days_min}–{top.delivery_days_max} days"
             if top.delivery_days_max is not None else "delivery unknown")
    out   = [f"**{top.platform_name}** is the best {mode.value} option at {price} (delivery: {del_})."]
    if len(ranked) > 1:
        r  = ranked[1]
        rp = f"₹{r.effective_price:,.0f}" if r.effective_price else "N/A"
        out.append(f"Runner-up: **{r.platform_name}** at {rp}.")
    cheapest = min((o for o in ranked if o.effective_price), key=lambda x: x.effective_price, default=None)
    if cheapest and cheapest != ranked[0]:
        out.append(f"💰 Cheapest: **{cheapest.platform_name}** at ₹{cheapest.effective_price:,.0f}.")
    return " ".join(out)


async def run_ranker(state: PipelineState) -> PipelineState:
    """Stage 5 — Score, rank, badge, and generate LLM explanation."""
    if not state.matched_offers:
        state.explanation = "No matching offers found after filtering."
        return state

    mode    = state.request.preferences.mode
    weights = _WEIGHTS[mode]
    offers  = state.matched_offers

    for o in offers:
        ps = _price_score(o, offers)
        ds = _delivery_score(o, offers)
        ts = _trust_score(o)
        o.score_breakdown = ScoreBreakdown(
            price_score=ps, delivery_score=ds, trust_score=ts,
            match_score=o.match_score,
            final_score=round(
                ps * weights["price"] + ds * weights["delivery"] + ts * weights["trust"], 3
            ),
            weights_used=weights,
        )

    ranked = sorted(offers, key=lambda x: x.score_breakdown.final_score, reverse=True)
    _assign_badges(ranked)
    state.ranked_offers = ranked

    # LLM explanation with template fallback
    query = (state.normalized_product.search_query
             if state.normalized_product else state.request.query or "")
    try:
        from app.agents.llm_ranker import llm_generate_explanation
        llm_exp = await llm_generate_explanation(ranked, mode, query)
        state.explanation = llm_exp or _template_explanation(ranked, mode)
    except Exception as e:
        logger.error(f"LLM explanation failed: {e}")
        state.explanation = _template_explanation(ranked, mode)

    logger.info(
        f"Ranker: {len(ranked)} ranked | top={ranked[0].platform_name} "
        f"score={ranked[0].score_breakdown.final_score} | mode={mode.value}"
    )
    return state
