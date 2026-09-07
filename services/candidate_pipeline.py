from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from services.candidate_band_policy import CandidateBandPolicy, apply_band_policy_to_records
from services.candidate_contract import CandidateRankingResult
from services.candidate_fund_adapter import candidates_from_turkiye_fund_scanner
from services.candidate_ranking import rank_candidates
from services.candidate_score_calibration import (
    CandidateCalibrationDiagnostic,
    candidate_score_calibration_diagnostic,
)
from services.candidate_wealth_facade import WealthCandidateFacade, wealth_candidate_facade

PIPELINE_VERSION = "candidate_pipeline_2"


@dataclass(frozen=True)
class CandidatePipelineResult:
    ranking: CandidateRankingResult
    wealth_facade: WealthCandidateFacade
    calibration: CandidateCalibrationDiagnostic
    band_policy_applied: bool
    pipeline_version: str = PIPELINE_VERSION
    persist: bool = False
    production_writes: tuple[str, ...] = ()
    eight_e_calls: int = 0
    new_money_calls: int = 0
    trades: int = 0
    portfolio_writes: int = 0


def run_turkiye_fund_candidate_pipeline(
    scanner_result: Any,
    intelligence_by_symbol: Mapping[str, Any],
    *,
    band_policy: Optional[CandidateBandPolicy] = None,
) -> CandidatePipelineResult:
    if bool(getattr(scanner_result, "persist", False)):
        raise ValueError("candidate_pipeline_refuses_persisted_scanner_result")
    if tuple(getattr(scanner_result, "production_writes", ()) or ()):
        raise ValueError("candidate_pipeline_refuses_scanner_production_writes")
    for field in ("eight_e_calls", "new_money_calls", "trades", "portfolio_writes"):
        if int(getattr(scanner_result, field, 0) or 0) != 0:
            raise ValueError(f"candidate_pipeline_refuses_scanner_{field}")

    records = candidates_from_turkiye_fund_scanner(
        scanner_result,
        intelligence_by_symbol,
    )

    calibration = candidate_score_calibration_diagnostic(records)

    if band_policy is not None:
        records = apply_band_policy_to_records(
            records,
            policy=band_policy,
        )

    ranking = rank_candidates(
        records,
        ranking_as_of=str(getattr(scanner_result, "as_of", "") or ""),
    )
    facade = wealth_candidate_facade(ranking)

    return CandidatePipelineResult(
        ranking=ranking,
        wealth_facade=facade,
        calibration=calibration,
        band_policy_applied=band_policy is not None,
        persist=False,
        production_writes=(),
        eight_e_calls=0,
        new_money_calls=0,
        trades=0,
        portfolio_writes=0,
    )
