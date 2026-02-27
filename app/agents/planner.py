from __future__ import annotations
import re
from typing import Optional, List, Tuple

from app.schemas import NormalizedProduct, ProductAttributes
from app.marketplaces.registry import marketplace_registry, MarketplaceConfig
from app.agents import PipelineState
from app.state import CompareState
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Regex constants ───────────────────────────────────────────────────────────
_BRANDS   = ["apple","samsung","oneplus","xiaomi","redmi","oppo","vivo","realme",
             "poco","google","motorola","nokia","lg","sony","asus","lenovo","hp","dell","acer"]
_STORAGES = re.compile(r'\b(\d+\s*(?:GB|TB))\b', re.IGNORECASE)
_RAMS     = re.compile(r'\b(\d+\s*GB)\s*RAM\b', re.IGNORECASE)
_COLORS   = ["black","white","blue","red","green","gold","silver","purple","pink",
             "yellow","titanium","natural","midnight","starlight","graphite"]


def _regex_parse(query: str) -> Tuple[ProductAttributes, str]:
    q  = query.strip()
    ql = q.lower()

    brand    = next((b.capitalize() for b in _BRANDS if b in ql), None)
    storages = list(dict.fromkeys(
        s.upper().replace(" ", "") for s in _STORAGES.findall(q)
    ))
    storage  = storages[0] if storages else None
    ram_m    = _RAMS.search(q)
    ram      = ram_m.group(1).upper().replace(" ", "") if ram_m else None
    color    = next((c.capitalize() for c in _COLORS if c in ql), None)

    # Model = query minus brand/storage/color/ram tokens
    model_str = q
    for part in ([brand] if brand else []) + (storages or []) + ([color] if color else []):
        model_str = re.sub(re.escape(part), '', model_str, flags=re.IGNORECASE)
    if ram_m:
        model_str = model_str.replace(ram_m.group(0), '')
    model = re.sub(r'\s{2,}', ' ', model_str).strip() or None

    category = "smartphone"
    if model:
        ml = model.lower()
        if any(w in ml for w in ["laptop","book","macbook"]):    category = "laptop"
        elif any(w in ml for w in ["tab","ipad","galaxy tab"]): category = "tablet"
        elif any(w in ml for w in ["watch","band"]):            category = "wearable"
        elif any(w in ml for w in ["tv","television"]):         category = "tv"

    search_query = f"{brand or ''} {model or ''} {storage or ''}".strip() or q
    attrs = ProductAttributes(
        brand=brand, model=model, storage=storage,
        ram=ram, color=color, category=category, raw_query=q,
    )
    return attrs, search_query


async def _llm_parse(query: str) -> Optional[Tuple[ProductAttributes, str]]:
    from app.utils.llm_client import llm_client

    system = """\
You are a product query parser for Indian e-commerce.
Return ONLY this JSON (no markdown):
{"brand":"","model":"","storage":null,"ram":null,"color":null,
 "variant":null,"category":"smartphone","optimized_search_query":""}

Rules:
- brand: capitalize first letter (Apple, Samsung)
- model: full model name without brand (iPhone 15, Galaxy S24 Ultra)
- storage: capacity like 128GB, 256GB, 1TB — or null
- category: smartphone|laptop|tablet|audio|wearable|tv|other
- optimized_search_query: best string for e-commerce (brand+model+storage)
"""
    result = await llm_client.complete_json(
        system=system, user=f"Query: {query}", use_fast_model=False
    )
    if not result:
        return None

    attrs = ProductAttributes(
        brand=result.get("brand") or None,
        model=result.get("model") or None,
        storage=result.get("storage") or None,
        ram=result.get("ram") or None,
        color=result.get("color") or None,
        variant=result.get("variant") or None,
        category=result.get("category", "smartphone"),
        raw_query=query,
    )
    search_query = result.get("optimized_search_query") or query
    return attrs, search_query


def _select_marketplaces(request, brand: Optional[str]) -> List[MarketplaceConfig]:
    if request.allowed_marketplaces:
        selected = marketplace_registry.filter_by_keys(request.allowed_marketplaces)
        if not selected:
            logger.warning("allowed_marketplaces matched nothing — using all enabled")
            selected = marketplace_registry.all_enabled()
    else:
        selected = marketplace_registry.all_enabled()

    # Brand affinity filter (e.g. Samsung Shop only for Samsung queries)
    if brand:
        filtered = []
        for m in selected:
            if m.brand_affinity:
                if brand.lower() in m.brand_affinity:
                    filtered.append(m)
                else:
                    logger.info(f"Skip [{m.key}]: brand_affinity={m.brand_affinity}")
            else:
                filtered.append(m)
        selected = filtered

    # Never return empty
    if not selected:
        logger.warning("Brand filter emptied marketplace list — fallback to all enabled")
        selected = marketplace_registry.all_enabled()

    logger.info(f"Selected {len(selected)} markets: {[m.key for m in selected]}")
    return selected


async def run_planner(state: PipelineState) -> PipelineState:
    """Stage 1 — Parse query with LLM, fall back to regex, select marketplaces."""
    req   = state.request
    query = req.query or req.product_url or ""

    if not query.strip():
        state.add_error("Planner: empty query")
        return state

    # LLM parse → regex fallback
    llm_result = await _llm_parse(query)
    if llm_result:
        attrs, search_query = llm_result
        logger.info(f"Planner [LLM]: {attrs.brand} | {attrs.model} | {attrs.storage} → '{search_query}'")
    else:
        attrs, search_query = _regex_parse(query)
        logger.info(f"Planner [regex]: {attrs.brand} | {attrs.model} | {attrs.storage} → '{search_query}'")

    state.normalized_product = NormalizedProduct(
        attributes=attrs,
        search_query=search_query,
        source_url=req.product_url,
        source_marketplace=None,
    )

    markets = _select_marketplaces(req, attrs.brand)
    state.selected_marketplace_keys = [m.key for m in markets]
    return state


# ── LangGraph node function ──────────────────────────────────────────────────


def _select_marketplace_keys(brand: Optional[str]) -> List[str]:
    """Select target marketplace keys based on brand affinity.
    Returns all enabled sites, filtered by brand affinity if applicable.
    """
    all_enabled = marketplace_registry.all_enabled()
    if not brand:
        return [m.key for m in all_enabled]

    filtered = []
    for m in all_enabled:
        if m.brand_affinity:
            if brand.lower() in m.brand_affinity:
                filtered.append(m)
        else:
            filtered.append(m)

    if not filtered:
        filtered = all_enabled

    return [m.key for m in filtered]


async def planner_node(state: dict) -> dict:
    """LangGraph node: Stage 1 — Parse query, select sites, handle retry.

    Retry behavior (when match_attempts > 0):
      match_attempts == 1 → drop storage constraint (storage = "")
      match_attempts == 2 → use base model only, no variants
      MUST reset raw_results and cleaned_results on retry
      MUST NOT reset match_attempts (Matcher owns this counter)
    """
    query = state.get("query", "")
    mode = state.get("mode", "balanced")
    match_attempts = state.get("match_attempts", 0)

    if not query.strip():
        return {
            "brand": "",
            "model": "",
            "storage": "",
            "target_sites": [],
            "normalized_product": NormalizedProduct(),
        }

    # Parse query with LLM → regex fallback
    llm_result = await _llm_parse(query)
    if llm_result:
        attrs, search_query = llm_result
        logger.info(
            "Planner [LLM] (attempt=%d): %s | %s | %s → '%s'",
            match_attempts, attrs.brand, attrs.model, attrs.storage, search_query,
        )
    else:
        attrs, search_query = _regex_parse(query)
        logger.info(
            "Planner [regex] (attempt=%d): %s | %s | %s → '%s'",
            match_attempts, attrs.brand, attrs.model, attrs.storage, search_query,
        )

    # ── Retry modifications ──────────────────────────────────────────────
    if match_attempts == 1:
        # Drop storage constraint
        attrs.storage = None
        search_query = f"{attrs.brand or ''} {attrs.model or ''}".strip() or query
        logger.info("Planner retry (attempt=1): dropped storage → '%s'", search_query)
    elif match_attempts >= 2:
        # Use base model only, no variants
        attrs.storage = None
        if attrs.variant:
            attrs.variant = None
        # Simplify to just brand + base model
        base_model = attrs.model or ""
        # Remove variant words from model name
        for v in ["ultra", "plus", "lite", "mini", "pro", "max", "fe", "edge", "neo"]:
            base_model = re.sub(rf'\b{v}\b', '', base_model, flags=re.IGNORECASE)
        base_model = re.sub(r'\s{2,}', ' ', base_model).strip()
        attrs.model = base_model
        search_query = f"{attrs.brand or ''} {base_model}".strip() or query
        logger.info("Planner retry (attempt=2): base model only → '%s'", search_query)

    # Build NormalizedProduct
    target_sites = _select_marketplace_keys(attrs.brand)
    normalized = NormalizedProduct(
        attributes=attrs,
        search_query=search_query,
        source_url=None,
        source_marketplace=None,
        brand=attrs.brand or "",
        model=attrs.model or "",
        storage=attrs.storage or "",
        raw_query=attrs.raw_query or query,
        target_sites=target_sites,
    )

    logger.info(
        "Planner ✓ — '%s %s' | sites=%d | attempt=%d",
        normalized.brand, normalized.model, len(target_sites), match_attempts,
    )

    result = {
        "brand": normalized.brand,
        "model": normalized.model,
        "storage": normalized.storage,
        "target_sites": target_sites,
        "normalized_product": normalized,
    }

    # On retry, MUST reset raw_results and cleaned_results
    # (raw_results/site_statuses use add_or_reset reducer: None → reset)
    if match_attempts > 0:
        result["raw_results"] = None        # triggers reset via add_or_reset
        result["site_statuses"] = None      # triggers reset via add_or_reset
        result["cleaned_results"] = []

    return result
