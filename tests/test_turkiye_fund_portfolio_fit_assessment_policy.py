from copy import deepcopy

import pytest

from services.turkiye_fund_portfolio_fit_assessment_policy import (
    Fund18AssessmentPolicyError,
    draft_fund18_assessment_policy_v1,
    normalize_fund18_assessment_policy,
)


def test_draft_policy_is_valid_for_simulation():
    policy = normalize_fund18_assessment_policy(
        draft_fund18_assessment_policy_v1()
    )

    assert policy.production_effective is False
    assert policy.human_approved is False
    assert policy.locked is False


def test_draft_policy_cannot_be_required_effective():
    with pytest.raises(
        Fund18AssessmentPolicyError,
        match="effective_policy_requires_human_approval",
    ):
        normalize_fund18_assessment_policy(
            draft_fund18_assessment_policy_v1(),
            require_effective=True,
        )


def test_effective_policy_requires_approval_and_lock():
    raw = draft_fund18_assessment_policy_v1()
    raw["production_effective"] = True

    with pytest.raises(
        Fund18AssessmentPolicyError,
        match="effective_policy_requires_human_approval",
    ):
        normalize_fund18_assessment_policy(raw)

    raw["human_approved"] = True

    with pytest.raises(
        Fund18AssessmentPolicyError,
        match="effective_policy_requires_lock",
    ):
        normalize_fund18_assessment_policy(raw)


def test_effective_policy_is_valid_when_fully_locked():
    raw = draft_fund18_assessment_policy_v1()
    raw["human_approved"] = True
    raw["locked"] = True
    raw["production_effective"] = True

    policy = normalize_fund18_assessment_policy(
        raw,
        require_effective=True,
    )

    assert policy.production_effective is True


def test_duplicate_role_mapping_rejected():
    raw = draft_fund18_assessment_policy_v1()
    raw["role_fit"]["rules"].append(
        deepcopy(raw["role_fit"]["rules"][0])
    )
    raw["role_fit"]["rules"][-1]["rule_id"] = "OTHER-ID"

    with pytest.raises(
        Fund18AssessmentPolicyError,
        match="duplicate_role_mapping",
    ):
        normalize_fund18_assessment_policy(raw)


def test_duplicate_rule_id_rejected():
    raw = draft_fund18_assessment_policy_v1()
    duplicate = deepcopy(raw["role_fit"]["rules"][1])
    duplicate["rule_id"] = raw["role_fit"]["rules"][0]["rule_id"]
    raw["role_fit"]["rules"].append(duplicate)

    with pytest.raises(
        Fund18AssessmentPolicyError,
        match="duplicate_rule_id",
    ):
        normalize_fund18_assessment_policy(raw)


def test_reversed_thresholds_rejected():
    raw = draft_fund18_assessment_policy_v1()
    raw["economic_overlap"]["low_upper_exclusive_pct"] = 40
    raw["economic_overlap"]["medium_upper_inclusive_pct"] = 35

    with pytest.raises(
        Fund18AssessmentPolicyError,
        match="economic_overlap_thresholds_reversed",
    ):
        normalize_fund18_assessment_policy(raw)


def test_unknown_renormalization_rejected():
    raw = draft_fund18_assessment_policy_v1()
    raw["economic_overlap"]["renormalize_unknown"] = True

    with pytest.raises(
        Fund18AssessmentPolicyError,
        match="economic_overlap_renormalization_forbidden",
    ):
        normalize_fund18_assessment_policy(raw)


def test_free_text_parsing_cannot_be_enabled():
    raw = draft_fund18_assessment_policy_v1()
    raw["fail_closed"]["parse_observed_fact"] = True

    with pytest.raises(
        Fund18AssessmentPolicyError,
        match="fail_closed_flag_invalid:parse_observed_fact",
    ):
        normalize_fund18_assessment_policy(raw)
