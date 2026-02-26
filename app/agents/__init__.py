from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List, Dict

from app.schemas import (
    CompareRequest, NormalizedProduct,
    RawListing, NormalizedOffer, SiteStatus,
)


@dataclass
class PipelineState:
    request:                   CompareRequest
    normalized_product:        Optional[NormalizedProduct]  = None
    selected_marketplace_keys: List[str]                    = field(default_factory=list)
    raw_listings:              List[RawListing]             = field(default_factory=list)
    raw_html_store:            Dict[str, str]               = field(default_factory=dict)
    normalized_offers:         List[NormalizedOffer]        = field(default_factory=list)
    matched_offers:            List[NormalizedOffer]        = field(default_factory=list)
    ranked_offers:             List[NormalizedOffer]        = field(default_factory=list)
    explanation:               str                          = ""
    site_statuses:             Dict[str, SiteStatus]        = field(default_factory=dict)
    errors:                    List[str]                    = field(default_factory=list)

    def add_error(self, msg: str):
        self.errors.append(msg)

    def set_site_status(self, s: SiteStatus):
        self.site_statuses[s.marketplace_key] = s

    def get_site_statuses_list(self) -> List[SiteStatus]:
        return list(self.site_statuses.values())
