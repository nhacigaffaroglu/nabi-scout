"""Turkish participation-fund universe and scanner contracts.

Scanner discovers and ranks research candidates. It does not own portfolio
allocation, position sizing, 8E, New Money, or Participation methodology.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

UNIVERSE_DISCOVERED = "DISCOVERED"
UNIVERSE_ACTIVE = "ACTIVE"
UNIVERSE_ANALYZABLE = "ANALYZABLE"
UNIVERSE_PARTICIPATION_ELIGIBLE = "PARTICIPATION_ELIGIBLE"
UNIVERSE_SCANNABLE = "SCANNABLE"
UNIVERSE_STATES = (
    UNIVERSE_DISCOVERED,
    UNIVERSE_ACTIVE,
    UNIVERSE_ANALYZABLE,
    UNIVERSE_PARTICIPATION_ELIGIBLE,
    UNIVERSE_SCANNABLE,
)

TEFAS_STATUS_ACTIVE = "ACTIVE"
TEFAS_STATUS_INACTIVE = "INACTIVE"
TEFAS_STATUS_UNPROVEN = "UNPROVEN"

SCANNER_READY = "READY"
SCANNER_PARTIAL = "PARTIAL"
SCANNER_REVIEW_REQUIRED = "REVIEW_REQUIRED"
SCANNER_BLOCKED = "BLOCKED"
SCANNER_STATES = (
    SCANNER_READY,
    SCANNER_PARTIAL,
    SCANNER_REVIEW_REQUIRED,
    SCANNER_BLOCKED,
)

EVIDENCE_KAP_TITLE_KATILIM = "KAP_TITLE_KATILIM"
EVIDENCE_KAP_UMBRELLA_KATILIM = "KAP_UMBRELLA_KATILIM"
EVIDENCE_TEFAS_CATEGORY_KATILIM = "TEFAS_CATEGORY_KATILIM"
EVIDENCE_TEFAS_IDENTITY = "TEFAS_CANONICAL_IDENTITY"
EVIDENCE_KAP_IDENTITY = "KAP_CANONICAL_IDENTITY"

PEER_VIEW_CATEGORY = "PEER_CATEGORY"
PEER_VIEW_OVERALL = "OVERALL_RESEARCH"

RANK_TIE_BREAK = (
    "fi_score_desc",
    "completeness_desc",
    "confidence_desc",
    "fund_code_asc",
)

SCANNER_NOT_A_BUY = (
    "Scanner rank is research-only. It is not a buy, increase-exposure, "
    "or New Money instruction."
)
SCANNER_NOT_EIGHT_E = "Scanner does not own 8E policy."
SCANNER_NOT_NEW_MONEY = "Scanner does not own New Money policy."
SCANNER_NOT_PARTICIPATION = "Scanner does not own Participation methodology."

INSTRUMENT_FUND = "FUND"
MARKET_TR = "TR"


@dataclass(frozen=True)
class TurkiyeFundUniverseIdentity:
    fund_code: str
    fund_name: Optional[str]
    isin: Optional[str]
    founder: Optional[str]
    instrument: str = INSTRUMENT_FUND
    market: str = MARKET_TR
    currency: Optional[str] = None
    umbrella_type: Optional[str] = None
    tefas_status: str = TEFAS_STATUS_UNPROVEN
    tefas_category: Optional[str] = None
    source_provenance: tuple[str, ...] = ()
    discovery_evidence: tuple[str, ...] = ()
    kap_publish_date: Optional[str] = None
    pdr_year: Optional[int] = None
    pdr_period: Optional[int] = None
    kap_disclosure_index: Optional[int] = None
    unit_price: Optional[float] = None
    price_date: Optional[str] = None
    fund_total_value: Optional[float] = None
    investor_count: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TurkiyeFundScannerRow:
    fund_code: str
    fund_name: Optional[str]
    category: str
    rank: Optional[int]
    fi_score: Optional[float]
    fi_state: Optional[str]
    confidence: Optional[float]
    participation: Optional[str]
    research_allowed: bool
    exposure: Optional[str]
    return_1y: Optional[float]
    max_drawdown: Optional[float]
    data_completeness: Optional[float]
    scanner_status: str
    universe_states: tuple[str, ...]
    reason: str
    missing_evidence: tuple[str, ...] = ()
    fi_profile: Optional[str] = None
    peer_view: str = PEER_VIEW_CATEGORY
    founder: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TurkiyeFundScannerResult:
    as_of: str
    calculated_at: str
    discovered_count: int
    active_count: int
    analyzable_count: int
    participation_uygun_count: int
    kontrol_et_count: int
    uygun_degil_count: int
    fi_ready_count: int
    scanner_ready_count: int
    review_required_count: int
    blocked_count: int
    identities: tuple[TurkiyeFundUniverseIdentity, ...] = ()
    sample_codes: tuple[str, ...] = ()
    rows: tuple[TurkiyeFundScannerRow, ...] = ()
    review_queue: tuple[TurkiyeFundScannerRow, ...] = ()
    ranked_by_category: dict[str, tuple[TurkiyeFundScannerRow, ...]] = field(default_factory=dict)
    overall_shortlist: tuple[TurkiyeFundScannerRow, ...] = ()
    profile_routing: tuple[tuple[str, int, tuple[str, ...]], ...] = ()
    production_reads: tuple[str, ...] = ()
    production_writes: tuple[str, ...] = ()
    eight_e_calls: int = 0
    new_money_calls: int = 0
    trades: int = 0
    portfolio_writes: int = 0
    persist: bool = False
    capture_stats: dict[str, Any] = field(default_factory=dict)
    coverage_funnel: dict[str, Any] = field(default_factory=dict)
    review_reason_counts: dict[str, int] = field(default_factory=dict)
    manager_coverage: dict[str, dict[str, int]] = field(default_factory=dict)
    category_coverage: dict[str, dict[str, int]] = field(default_factory=dict)
    fi_distribution: dict[str, int] = field(default_factory=dict)
    pdr_parser_quality: dict[str, Any] = field(default_factory=dict)
    limitations: tuple[str, ...] = (
        SCANNER_NOT_A_BUY,
        SCANNER_NOT_EIGHT_E,
        SCANNER_NOT_NEW_MONEY,
        SCANNER_NOT_PARTICIPATION,
    )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["identities"] = [row.to_dict() for row in self.identities]
        payload["rows"] = [row.to_dict() for row in self.rows]
        payload["review_queue"] = [row.to_dict() for row in self.review_queue]
        payload["ranked_by_category"] = {
            key: [row.to_dict() for row in value]
            for key, value in self.ranked_by_category.items()
        }
        payload["overall_shortlist"] = [row.to_dict() for row in self.overall_shortlist]
        return payload
