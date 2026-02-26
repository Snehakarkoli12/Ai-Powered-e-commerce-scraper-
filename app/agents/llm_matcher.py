from __future__ import annotations
from typing import Optional, Dict
from app.utils.llm_client import llm_client
from app.utils.logger import get_logger

logger = get_logger(__name__)

_MATCH_SYSTEM = """\
You are a product matching expert for Indian e-commerce.

match_score guide:
1.00 = Perfect: brand + model + storage + color all match
0.85 = Good: brand + model + storage match; color differs
0.70 = OK: brand + model match; storage differs
0.50 = Weak: same product family but different variant (iPhone 15 Pro ≠ iPhone 15)
0.20 = Poor: same brand, different model generation (iPhone 13 ≠ iPhone 15)
0.00 = No match: completely different product OR is an accessory

CRITICAL: is_correct_model = false when model numbers differ (13≠15, S23≠S24).
is_accessory = true for cases/covers/chargers/cables/earphones/screen protectors.

Return ONLY this JSON:
{"match_score":0.0,"is_correct_model":true,"is_correct_storage":true,"is_accessory":false,"reason":""}
"""


async def llm_compute_match(
    listing_title:  str,
    target_brand:   Optional[str],
    target_model:   Optional[str],
    target_storage: Optional[str],
    target_color:   Optional[str],
) -> Optional[Dict]:
    """Semantic match — called only when regex score is uncertain (0.3–0.75)."""
    user = (
        f"Target: brand={target_brand or 'any'}, model={target_model or 'any'}, "
        f"storage={target_storage or 'any'}, color={target_color or 'any'}\n"
        f"Listing: \"{listing_title}\""
    )
    result = await llm_client.complete_json(
        system=_MATCH_SYSTEM, user=user, use_fast_model=False,
    )
    if result:
        logger.debug(
            f"LLM match: score={result.get('match_score')} "
            f"correct_model={result.get('is_correct_model')} — {result.get('reason','')[:50]}"
        )
    return result
