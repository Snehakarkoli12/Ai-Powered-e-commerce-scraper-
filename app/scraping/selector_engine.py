from __future__ import annotations
from typing import Optional, Dict, List
from playwright.async_api import Page, ElementHandle
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Universal fallback patterns — ordered most to least stable ────────────────
UNIVERSAL: Dict[str, List[str]] = {
    "container": [
        "[data-component-type='s-search-result']",
        "[data-id]",
        "[data-product-id]",
        "[data-testid*='product']",
        "li.product-item",
        "div.product-item",
        "article.product",
        "[class*='ProductCard']",
        "[class*='product-card']",
        "[class*='ProductModule']",
        "[class*='product-tile']",
        "[class*='item-card']",
        "[class*='search-result']",
        "[class*='SearchResult']",
        "[class*='product-listing']",
        "[class*='productCard']",
        "[class*='product-box']",
        "[class*='plp-card']",
        "li[class*='product']",
        "div[class*='product'][class*='list']",
        "div[class*='product'][class*='grid']",
    ],
    "title": [
        "h2 .a-text-normal", "h2 a", "h3 a", "h2 span", "h3 span",
        "[class*='title'] a", "[class*='Title'] a",
        "[class*='name'] a",  "[class*='Name'] a",
        "[class*='product-title']", "[class*='ProductTitle']",
        "[class*='product-name']",  "[class*='ProductName']",
        "a[class*='title']", "a[class*='name']",
        "[class*='productTitle']",
    ],
    "price": [
        ".a-price .a-offscreen",
        "[class*='discountedPrice']", "[class*='DiscountedPrice']",
        "[class*='selling-price']",  "[class*='SellingPrice']",
        "[class*='final-price']",    "[class*='FinalPrice']",
        "[class*='sp__price']",
        "span[class*='Price']",
        "div[class*='Price']",
        "[class*='price']",
        "[class*='amount']",
    ],
    "original_price": [
        ".a-text-price .a-offscreen",
        "[class*='originalPrice']", "[class*='OriginalPrice']",
        "[class*='old-price']",     "[class*='OldPrice']",
        "[class*='mrp']",           "[class*='MRP']",
        "[class*='strikethrough']", "del", "s",
    ],
    "rating": [
        ".a-icon-star-small .a-icon-alt", ".a-icon-star .a-icon-alt",
        "[aria-label*='out of 5']",
        "[aria-label*='stars']",
        "[class*='rating'][class*='value']",
        "[class*='Rating'][class*='Value']",
        "[class*='rating']",
    ],
    "review_count": [
        "[aria-label*='ratings'] .a-size-small",
        "[class*='review'][class*='count']",
        "[class*='ReviewCount']",
        "[class*='rating-count']",
        "span[class*='review']",
        "[class*='ratings']",
    ],
    "listing_url": [
        "h2 a", "a[href*='/dp/']", "a[href*='/p/']",
        "a[href*='/product']", "a[href*='/buy']",
        "a[class*='product']", "a[class*='title']",
        "a[href*='/pd/']", "a[href*='/item/']",
    ],
    "delivery": [
        "[data-cy='delivery-recipe-content'] .a-text-bold",
        "[class*='delivery']", "[class*='Delivery']",
        "[class*='dispatch']", "[class*='shipping']",
        "[class*='arrival']",  "[class*='estimated']",
        "[class*='deliveryTime']",
    ],
    "shipping": [
        "[class*='shipping']", "[class*='Shipping']",
        "[class*='free-shipping']", "[class*='delivery-fee']",
    ],
    "seller": [
        "a[href*='seller']", "[class*='seller']",
        "[class*='Seller']", "[class*='sold-by']",
    ],
}


class SelectorEngine:
    """
    Multi-strategy selector engine:
    cache → YAML primary → YAML fallback → universal heuristics → JS text search
    All discoveries cached per domain for session lifetime.
    """

    def __init__(self):
        self._cache: Dict[str, str] = {}

    def _key(self, domain: str, field: str) -> str:
        return f"{domain}::{field}"

    def _get_cached(self, domain: str, field: str) -> Optional[str]:
        return self._cache.get(self._key(domain, field))

    def _save(self, domain: str, field: str, selector: str):
        k = self._key(domain, field)
        if k not in self._cache:
            self._cache[k] = selector
            logger.info(f"[SelectorEngine] Discovered [{domain}] {field} → '{selector}'")

    async def resolve_container(
        self, page: Page, domain: str,
        primary: Optional[str], fallback: Optional[str],
    ) -> Optional[str]:
        cached = self._get_cached(domain, "container")
        if cached:
            elems = await page.query_selector_all(cached)
            if elems:
                return cached
            del self._cache[self._key(domain, "container")]

        candidates = [s for s in [primary, fallback] if s]
        candidates += UNIVERSAL["container"]

        for sel in candidates:
            try:
                elems = await page.query_selector_all(sel)
                if len(elems) >= 2:
                    self._save(domain, "container", sel)
                    logger.debug(f"[{domain}] container='{sel}' ({len(elems)} items)")
                    return sel
            except Exception:
                continue
        return None

    async def get_text(
        self, card: ElementHandle, domain: str, field: str,
        primary: Optional[str], fallback: Optional[str],
    ) -> Optional[str]:
        cached = self._get_cached(domain, field)
        candidates: List[str] = []
        if cached:
            candidates.append(cached)
        candidates += [s for s in [primary, fallback] if s and s != cached]
        candidates += UNIVERSAL.get(field, [])

        for sel in candidates:
            try:
                elem = await card.query_selector(sel)
                if elem:
                    # text_content() returns text even from CSS-hidden elements (.a-offscreen)
                    text = (await elem.inner_text()).strip()
                    if not text:
                        text = ((await elem.text_content()) or "").strip()
                    if text:
                        if sel not in [primary, fallback, cached]:
                            self._save(domain, field, sel)
                        return text
            except Exception:
                continue

        if field == "price":
            return await self._js_find_price(card)
        return None

    async def get_attr(
        self, card: ElementHandle, domain: str, field: str,
        attr: str, primary: Optional[str], fallback: Optional[str],
    ) -> Optional[str]:
        cache_key = f"{field}:{attr}"
        cached    = self._get_cached(domain, cache_key)
        candidates: List[str] = []
        if cached:
            candidates.append(cached)
        candidates += [s for s in [primary, fallback] if s and s != cached]
        candidates += UNIVERSAL.get(field, [])

        for sel in candidates:
            try:
                elem = await card.query_selector(sel)
                if elem:
                    val = await elem.get_attribute(attr)
                    if val and val.strip():
                        val = val.strip()
                        if sel not in [primary, fallback, cached]:
                            self._save(domain, cache_key, sel)
                        return val
            except Exception:
                continue
        return None

    async def _js_find_price(self, card: ElementHandle) -> Optional[str]:
        try:
            return await card.evaluate("""el => {
                const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null, false);
                while (walker.nextNode()) {
                    const t = walker.currentNode.textContent.trim();
                    if (t.includes('₹') && /\\d{3,}/.test(t)) return t;
                }
                for (const node of el.querySelectorAll('*')) {
                    if (node.childNodes.length === 1 && node.childNodes[0].nodeType === 3) {
                        const t = node.textContent.trim();
                        if (t.match(/^[₹Rs.\\s]*[\\d,]+(\\.\\d+)?$/) && t.length < 20) return t;
                    }
                }
                return null;
            }""")
        except Exception:
            return None

    def dump_cache(self) -> dict:
        return dict(self._cache)


selector_engine = SelectorEngine()
