from __future__ import annotations

from pathlib import Path


PAGE = Path("pages/13_Turkiye_Fon_Tarama.py")


def test_page_13_uses_read_only_review_intelligence_between_reason_and_queue_sections():
    source = PAGE.read_text(encoding="utf-8")

    assert (
        "from services.turkiye_fund_review_intelligence import "
        "build_review_intelligence"
    ) in source
    assert 'st.subheader("İnceleme zekâsı")' in source
    assert "build_review_intelligence(payload).to_dict()" in source

    canonical_index = source.index('st.subheader("İnceleme nedenleri")')
    intelligence_index = source.index('st.subheader("İnceleme zekâsı")')
    queue_index = source.index('st.subheader("İnceleme kuyruğu")')
    assert canonical_index < intelligence_index < queue_index


def test_page_13_review_intelligence_does_not_gain_execution_authority():
    source = PAGE.read_text(encoding="utf-8")

    intelligence_block = source.split('st.subheader("İnceleme zekâsı")', 1)[1]
    intelligence_block = intelligence_block.split(
        'st.subheader("İnceleme kuyruğu")', 1
    )[0]

    forbidden = (
        "git add",
        "commit(",
        "push(",
        "place_order",
        "new_money",
        "portfolio_writes",
    )
    for token in forbidden:
        assert token not in intelligence_block.lower()
