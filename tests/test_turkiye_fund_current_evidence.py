from dataclasses import dataclass

from services.turkiye_fund_current_evidence import filter_current_packs


@dataclass
class _Identity:
    fund_code: str
    kap_disclosure_index: int = 0


def test_matching_current_pack_is_kept():
    current, quarantined = filter_current_packs(
        {
            "GKV": {
                "kap_disclosure_index": 12,
            }
        },
        [_Identity("GKV", 12)],
    )

    assert set(current) == {"GKV"}
    assert quarantined == ()


def test_advanced_disclosure_quarantines_stale_pack():
    current, quarantined = filter_current_packs(
        {
            "GKV": {
                "kap_disclosure_index": 11,
            }
        },
        [_Identity("GKV", 12)],
    )

    assert current == {}
    assert quarantined == ("GKV",)


def test_pack_without_current_identity_is_not_used():
    current, quarantined = filter_current_packs(
        {
            "GKV": {
                "kap_disclosure_index": 12,
            }
        },
        [_Identity("IAT", 3)],
    )

    assert current == {}
    assert quarantined == ()


def test_zero_expected_index_does_not_invent_freshness_requirement():
    current, quarantined = filter_current_packs(
        {
            "GKV": {
                "kap_disclosure_index": 9,
            }
        },
        [_Identity("GKV", 0)],
    )

    assert set(current) == {"GKV"}
    assert quarantined == ()


def test_pilot_frozen_pack_remains_explicitly_allowed():
    current, quarantined = filter_current_packs(
        {
            "GKV": {
                "pilot_frozen": True,
                "kap_disclosure_index": 1,
            }
        },
        [_Identity("GKV", 99)],
    )

    assert set(current) == {"GKV"}
    assert quarantined == ()


def test_codes_are_normalized():
    current, quarantined = filter_current_packs(
        {
            "gkv": {
                "kap_disclosure_index": 12,
            }
        },
        [_Identity("GKV", 12)],
    )

    assert set(current) == {"GKV"}
    assert quarantined == ()
