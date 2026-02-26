from __future__ import annotations
import asyncio
import re
from typing import Optional, Dict, List, Tuple

from app.schemas import NormalizedOffer, NormalizedProduct
from app.agents import PipelineState
from app.utils.logger import get_logger

logger = get_logger(__name__)

_ACCESSORY_KW = [
    'case','cover','screen protector','tempered glass','charger','cable','adapter',
    'earphone','earbud','skin','flip cover','stand','holder','pouch','sleeve',
    'bumper','shell','film','guard','dock','power bank','hub','tripod',
    'selfie stick','lens','mount','wallet case',
]
_WEIGHTS = {'brand': 0.30, 'model': 0.40, 'storage': 0.20, 'color': 0.10}


def _is_accessory(title: str) -> bool:
    t = title.lower()
    return any(k in t for k in _ACCESSORY_KW)


def _storage_gb(text: Optional[str]) -> Optional[int]:
    if not text: return None
    m = re.search(r'(\d+)\s*(GB|TB)', text, re.IGNORECASE)
    if m:
        v, u = int(m.group(1)), m.group(2).upper()
        return v * 1024 if u == 'TB' else v
    return None


def _regex_match(title: str, product: NormalizedProduct) -> Tuple[float, bool]:
    attrs = product.attributes
    tl    = title.lower()
    score = 0.0

    # Brand
    if attrs.brand:
        score += _WEIGHTS['brand'] if attrs.brand.lower() in tl else 0.0
    else:
        score += _WEIGHTS['brand']

    # Model — strict numeric check
    if attrs.model:
        ml = attrs.model.lower().strip()
        if re.search(r'\b' + re.escape(ml) + r'\b', tl):
            score += _WEIGHTS['model']
        else:
            nums_in_title = re.findall(r'\b(\d{2,})\b', tl)
            target_nums   = re.findall(r'\b(\d{2,})\b', ml)
            if target_nums and nums_in_title:
                for tn in target_nums:
                    for n in nums_in_title:
                        if n != tn and len(n) == len(tn):
                            return 0.0, True  # hard reject — model number mismatch
            tokens = ml.split()
            hit    = sum(1 for t in tokens if t in tl)
            score += _WEIGHTS['model'] * (hit / len(tokens) if tokens else 0)
    else:
        score += _WEIGHTS['model']

    # Storage
    if attrs.storage:
        tg = _storage_gb(attrs.storage)
        sm = re.search(r'(\d+\s*(?:GB|TB))', title, re.IGNORECASE)
        if sm:
            og = _storage_gb(sm.group(0))
            if tg and og:
                score += _WEIGHTS['storage'] if tg == og else (
                    _WEIGHTS['storage'] * min(tg, og) / max(tg, og)
                )
        else:
            score += _WEIGHTS['storage'] * 0.5
    else:
        score += _WEIGHTS['storage']

    # Color
    if attrs.color:
        score += _WEIGHTS['color'] if attrs.color.lower() in tl else 0.0
    else:
        score += _WEIGHTS['color']

    return round(min(score, 1.0), 3), False


def _deduplicate(offers: List[NormalizedOffer]) -> List[NormalizedOffer]:
    best: Dict[Tuple[str, Optional[float]], NormalizedOffer] = {}
    for o in sorted(offers, key=lambda x: x.match_score, reverse=True):
        k = (o.platform_key, o.effective_price)
        if k not in best:
            best[k] = o
    return list(best.values())


async def _score_one(
    offer: NormalizedOffer,
    product: NormalizedProduct,
    min_score: float,
) -> Tuple[NormalizedOffer, Optional[str]]:
    """Returns (offer, rejection_reason). None reason = accepted."""
    if _is_accessory(offer.title):
        return offer, "ACCESSORY"
    if offer.effective_price is None:
        return offer, "NO_PRICE"

    regex_score, hard_reject = _regex_match(offer.title, product)
    if hard_reject:
        return offer, "HARD_REJECT(model_mismatch)"

    final_score = regex_score

    # LLM for uncertain scores (0.3–0.75 range)
    from app.utils.llm_client import llm_client
    if llm_client.enabled and 0.3 < regex_score < 0.75:
        try:
            from app.agents.llm_matcher import llm_compute_match
            attrs  = product.attributes
            result = await llm_compute_match(
                offer.title, attrs.brand, attrs.model, attrs.storage, attrs.color
            )
            if result:
                if result.get("is_accessory"):
                    return offer, "LLM_ACCESSORY"
                if not result.get("is_correct_model", True):
                    return offer, "LLM_WRONG_MODEL"
                final_score = result.get("match_score", regex_score)
                logger.debug(
                    f"[{offer.platform_key}] regex={regex_score:.2f}→llm={final_score:.2f} "
                    f"| {result.get('reason','')[:50]}"
                )
        except Exception as e:
            logger.error(f"LLM matcher error: {e}")

    offer.match_score = final_score
    if final_score < min_score:
        return offer, f"LOW_SCORE({final_score:.2f})"
    return offer, None


async def run_matcher(state: PipelineState) -> PipelineState:
    """Stage 4 — Semantic product matching with LLM fallback."""
    if not state.normalized_offers or not state.normalized_product:
        logger.warning("Matcher: nothing to process")
        return state

    product   = state.normalized_product
    min_score = state.request.preferences.min_match_score

    results = await asyncio.gather(*[
        _score_one(o, product, min_score)
        for o in state.normalized_offers
    ])

    matched, rejections = [], []
    for offer, reason in results:
        if reason:
            rejections.append(f"[{offer.platform_key}] {reason}: {offer.title[:50]}")
        else:
            matched.append(offer)

    if rejections:
        logger.info(f"Rejected {len(rejections)} offers:")
        for r in rejections[:6]:
            logger.info(f"  ✗ {r}")

    if not matched and rejections:
        state.add_error(
            f"All {len(rejections)} offers rejected. "
            f"Try lowering min_match_score (current={min_score}). "
            f"Sample: {rejections[0]}"
        )

    state.matched_offers = _deduplicate(matched)
    logger.info(f"Matcher: ✓ {len(state.matched_offers)} matched, ✗ {len(rejections)} rejected")
    return state
