# -*- coding: utf-8 -*-
"""
Explainer agent — generates human-readable recommendation using Groq Llama 3.3 70B.

LangGraph node: explainer_node(state) → {final_response: {...}}
Backward compat: llm_generate_explanation(offers, mode, query) → str
"""
from __future__ import annotations
from typing import List, Optional
from app.schemas import NormalizedOffer, RankingMode, SiteStatus
from app.utils.llm_client import llm_client
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ── Master prompt compliant: 3-5 sentences, price diff, mode-aware ───────────

_EXPLAIN_SYSTEM = """\
You are a friendly Indian e-commerce shopping assistant.
Write a 3-5 sentence recommendation paragraph for the user.

RULES:
- Explain which offer is best and WHY for the user's preference mode.
- Mention the EXACT price difference between the top 2 offers (in ₹).
- Include delivery speed and seller trust context.
- Mode-aware reasoning:
  - cheapest: emphasize price savings and value.
  - fastest: emphasize delivery speed and convenience.
  - reliable: emphasize rating and seller trust.
  - balanced: balanced commentary across all factors.
- Use ₹ for prices (e.g. ₹49,999). Be conversational, no bullet points.
- Max 120 words. No markdown. No extra formatting.
"""


async def llm_generate_explanation(
    ranked_offers: List[NormalizedOffer],
    mode:          RankingMode,
    product_query: str,
) -> Optional[str]:
    """Generate explanation text using Groq Llama 3.3 70B Versatile."""
    if not ranked_offers:
        return None

    top = ranked_offers[0]
    lines = []
    for o in ranked_offers[:5]:
        p = f"₹{o.effective_price:,.0f}" if o.effective_price else "N/A"
        d = f"{o.delivery_days_max}d" if o.delivery_days_max is not None else "?"
        r = str(o.seller_rating or o.rating or "?")
        badge = f" [{', '.join(o.badges)}]" if o.badges else ""
        lines.append(
            f"- {o.platform_name or o.platform_key}: {p} | delivery:{d} | "
            f"rating:{r}/5 | match:{int(o.match_score*100)}%{badge}"
        )

    # Compute price diff between top 2
    price_diff_note = ""
    if len(ranked_offers) >= 2:
        p1 = ranked_offers[0].effective_price
        p2 = ranked_offers[1].effective_price
        if p1 is not None and p2 is not None:
            diff = abs(p2 - p1)
            price_diff_note = f" Price difference between top 2: ₹{diff:,.0f}."

    top_price = f"₹{top.effective_price:,.0f}" if top.effective_price else "price unknown"
    user = (
        f"Product: {product_query}\nPreference: {mode.value}\n\n"
        f"Ranked offers:\n" + "\n".join(lines) +
        f"\n\n{price_diff_note}"
        f"\nRecommend {top.platform_name or top.platform_key} at {top_price}. "
        f"Write 3-5 sentences."
    )

    result = await llm_client.complete_text(
        system=_EXPLAIN_SYSTEM,
        user=user,
        use_fast_model=False,  # Groq Llama 3.3 70B per master prompt
        max_tokens=200,
    )
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# LangGraph node function
# ═══════════════════════════════════════════════════════════════════════════════


async def explainer_node(state: dict) -> dict:
    """LangGraph node: Stage 6 — Generate final response with LLM explanation.

    Model: Groq → Meta Llama 3.3 70B Versatile
    Input: ranked_results + query + mode + site_statuses
    Output: final_response dict with ranked_offers, site_statuses, explanation, best_deal
    """
    ranked_results = state.get("ranked_results", [])
    query = state.get("query", "")
    mode_str = state.get("mode", "balanced")
    site_statuses = state.get("site_statuses", [])

    try:
        mode = RankingMode(mode_str)
    except ValueError:
        mode = RankingMode.balanced

    # Generate LLM explanation
    explanation = ""
    if ranked_results:
        try:
            explanation = await llm_generate_explanation(
                ranked_results, mode, query,
            ) or ""
            if explanation:
                logger.info("Explainer: generated %d chars", len(explanation))
        except Exception as e:
            logger.warning("Explainer: LLM failed: %s", str(e)[:80])
            explanation = ""
    else:
        # Graceful failure — no matching products found
        explanation = (
            "No matching products found for your query. "
            "Try a broader search term."
        )
        logger.info("Explainer: empty ranked_results — graceful failure message")

    # Build final_response dict per master prompt
    final_response = {
        "ranked_offers": ranked_results,
        "site_statuses": site_statuses,
        "explanation": explanation,
        "best_deal": ranked_results[0] if ranked_results else None,
    }

    return {"final_response": final_response}
