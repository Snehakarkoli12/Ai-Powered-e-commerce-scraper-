from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Dict
import yaml
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class SelectorConfig:
    primary:  Optional[str]
    fallback: Optional[str] = None


@dataclass
class MarketplaceSelectors:
    search_results_container: Optional[str]
    title:          SelectorConfig = field(default_factory=lambda: SelectorConfig(None))
    price:          SelectorConfig = field(default_factory=lambda: SelectorConfig(None))
    original_price: SelectorConfig = field(default_factory=lambda: SelectorConfig(None))
    rating:         SelectorConfig = field(default_factory=lambda: SelectorConfig(None))
    review_count:   SelectorConfig = field(default_factory=lambda: SelectorConfig(None))
    listing_url:    SelectorConfig = field(default_factory=lambda: SelectorConfig(None))
    delivery:       SelectorConfig = field(default_factory=lambda: SelectorConfig(None))
    shipping:       SelectorConfig = field(default_factory=lambda: SelectorConfig(None))
    seller:         Optional[SelectorConfig] = None


@dataclass
class MarketplaceConfig:
    key:                   str
    name:                  str
    enabled:               bool
    base_url:              str
    search_url_pattern:    str
    trust_score_base:      float
    selectors:             MarketplaceSelectors
    bot_detection_phrases: List[str]
    max_results:           int              = 5
    request_delay_ms:      Tuple[int, int]  = (700, 1400)
    scraper_module:        Optional[str]    = None
    wait_strategy:         str              = "domcontentloaded"
    needs_scroll:          bool             = True
    ready_selector:        Optional[str]    = None
    brand_affinity:        List[str]        = field(default_factory=list)


def _sel(data: dict, key: str) -> SelectorConfig:
    v = data.get(key, {}) or {}
    if isinstance(v, str):
        return SelectorConfig(primary=v)
    return SelectorConfig(
        primary=v.get("primary"),
        fallback=v.get("fallback"),
    )


def _load(raw: dict) -> MarketplaceConfig:
    s    = raw.get("selectors", {}) or {}
    sels = MarketplaceSelectors(
        search_results_container=s.get("search_results_container"),
        title=_sel(s, "title"),
        price=_sel(s, "price"),
        original_price=_sel(s, "original_price"),
        rating=_sel(s, "rating"),
        review_count=_sel(s, "review_count"),
        listing_url=_sel(s, "listing_url"),
        delivery=_sel(s, "delivery"),
        shipping=_sel(s, "shipping"),
        seller=_sel(s, "seller") if "seller" in s else None,
    )
    delay = raw.get("request_delay_ms", [700, 1400])
    return MarketplaceConfig(
        key=raw["key"],
        name=raw["name"],
        enabled=raw.get("enabled", True),
        base_url=raw["base_url"],
        search_url_pattern=raw["search_url_pattern"],
        trust_score_base=float(raw.get("trust_score_base", 0.7)),
        selectors=sels,
        bot_detection_phrases=raw.get("bot_detection_phrases", []),
        max_results=int(raw.get("max_results", 5)),
        request_delay_ms=(int(delay[0]), int(delay[1])),
        scraper_module=raw.get("scraper_module"),
        wait_strategy=raw.get("wait_strategy", "domcontentloaded"),
        needs_scroll=raw.get("needs_scroll", True),
        ready_selector=raw.get("ready_selector"),
        brand_affinity=[b.lower() for b in raw.get("brand_affinity", [])],
    )


class MarketplaceRegistry:
    def __init__(self, configs_dir: str):
        self._dir     = configs_dir
        self._configs: Dict[str, MarketplaceConfig] = {}
        self.reload()

    def reload(self):
        self._configs.clear()
        if not os.path.isdir(self._dir):
            logger.warning(f"Configs dir not found: {self._dir}")
            return
        for fname in sorted(os.listdir(self._dir)):
            if not fname.endswith(".yaml"):
                continue
            path = os.path.join(self._dir, fname)
            try:
                with open(path, encoding="utf-8") as f:
                    raw = yaml.safe_load(f)
                if raw and raw.get("key"):
                    cfg = _load(raw)
                    self._configs[cfg.key] = cfg
                    logger.debug(f"Loaded marketplace: {cfg.key} ({cfg.name})")
            except Exception as e:
                logger.error(f"Failed to load {fname}: {e}")
        logger.info(f"Registry: {len(self._configs)} marketplaces loaded")

    def all(self) -> List[MarketplaceConfig]:
        return list(self._configs.values())

    def all_enabled(self) -> List[MarketplaceConfig]:
        return [c for c in self._configs.values() if c.enabled]

    def get(self, key: str) -> Optional[MarketplaceConfig]:
        return self._configs.get(key)

    def filter_by_keys(self, keys: List[str]) -> List[MarketplaceConfig]:
        return [self._configs[k] for k in keys if k in self._configs and self._configs[k].enabled]


from app.config import settings
marketplace_registry = MarketplaceRegistry(settings.marketplaces_dir)
