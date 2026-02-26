from __future__ import annotations
from typing import Optional, Dict
from app.utils.llm_client import llm_client
from app.utils.logger import get_logger

logger = get_logger(__name__)

_EXTRACT_SYSTEM = """\
You are an Indian e-commerce product data extractor. Given raw text from a single product card, extract fields as JSON.

RULES:
- price: current selling price as float in INR (strip ₹ Rs commas). null if absent.
- original_price: MRP/strikethrough price as float. null if absent.
- delivery_days_max: max delivery days as int ("3-5 days"→5, "tomorrow"→1, "today"→0). null if absent.
- seller_rating: rating out of 5 as float. null if absent.
- review_count: number of ratings/reviews as int. null if absent.
- title: clean product name (brand+model+storage+color). Remove: "Add to Compare" "Coming Soon" "Sponsored".
- is_accessory: true ONLY for case/cover/screen protector/charger/cable/earphone — NOT the device itself.

Return ONLY this JSON (no markdown, no explanation):
{"title":"","price":null,"original_price":null,"delivery_days_max":null,"seller_rating":null,"review_count":null,"is_accessory":false}
"""

_SELECTOR_SYSTEM = """\
You are a web scraping expert for Indian e-commerce. Analyze the HTML and find stable CSS selectors for product listings.

RULES:
- Prefer [data-*] attributes over class names (most stable)
- Prefer [class*="keyword"] patterns over exact hash-based classes
- container: selector matching each individual product card (must match 2+ elements)
- title: selector for product name (relative to container)
- price: selector for current/discounted price (relative to container)
- original_price: selector for MRP/was-price (relative to container), null if none
- listing_url: selector for the product <a> link (relative to container)

Return ONLY this JSON:
{"container":"","title":"","price":"","original_price":null,"listing_url":""}
"""


async def llm_extract_card(card_text: str, platform_key: str) -> Optional[Dict]:
    """Fast model — runs per card when CSS extraction returns null price."""
    if not card_text or len(card_text.strip()) < 5:
        return None
    result = await llm_client.complete_json(
        system=_EXTRACT_SYSTEM,
        user=f"Platform: {platform_key}\nCard:\n{card_text[:500]}",
        use_fast_model=True,
    )
    if result:
        logger.debug(f"LLM card [{platform_key}] → price={result.get('price')} title={str(result.get('title',''))[:40]}")
    return result


async def llm_discover_selectors(raw_html: str, platform_key: str) -> Optional[Dict]:
    """Primary model — discovers CSS selectors when all heuristics fail."""
    if not raw_html:
        return None
    # Take a 4K window from the body (skip head/nav)
    snippet = raw_html[2000:7000] if len(raw_html) > 7000 else raw_html
    result = await llm_client.complete_json(
        system=_SELECTOR_SYSTEM,
        user=f"Site: {platform_key}\nHTML:\n{snippet}",
        use_fast_model=False,
    )
    if result:
        logger.info(f"LLM selectors [{platform_key}]: {result}")
    return result
