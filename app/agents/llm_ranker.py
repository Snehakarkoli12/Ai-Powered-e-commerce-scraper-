from __future__ import annotations
from typing import List, Optional
from app.schemas import NormalizedOffer, PreferenceMode
from app.utils.llm_client import llm_client
from app.utils.logger import get_logger

logger = get_logger(__name__)

_EXPLAIN_SYSTEM = """\
You are a friendly Indian e-commerce shopping assistant.
Write a 2-3 sentence recommendation for the top product offer.

RULES:
- Explain WHY it's the best for the user's preference
- Mention the price gap vs alternatives
- Note any key trade-off (delivery speed, trust, price)
- Use ₹ for rupees. Be conversational. Max 80 words. No bullet points.
"""


async def llm_generate_explanation(
    ranked_offers: List[NormalizedOffer],
    mode:          PreferenceMode,
    product_query: str,
) -> Optional[str]:
    if not ranked_offers:
        return None

    top   = ranked_offers
    lines = []
    for o in ranked_offers[:5]:
        p = f"₹{o.effective_price:,.0f}" if o.effective_price else "N/A"
        d = f"{o.delivery_days_max}d"    if o.delivery_days_max is not None else "?"
        r = str(o.seller_rating)         if o.seller_rating else "?"
        badge = f" [{o.recommendation_note}]" if o.recommendation_note else ""
        lines.append(f"- {o.platform_name}: {p} | del:{d} | rating:{r}/5 | match:{int(o.match_score*100)}%{badge}")

    user = (
        f"Product: {product_query}\nPreference: {mode.value}\n\n"
        f"Ranked offers:\n" + "\n".join(lines) +
        f"\n\nRecommend {top.platform_name} at ₹{top.effective_price:,.0f}."
    )
    result = await llm_client.complete_text(
        system=_EXPLAIN_SYSTEM, user=user, use_fast_model=False, max_tokens=150,
    )
    return result
