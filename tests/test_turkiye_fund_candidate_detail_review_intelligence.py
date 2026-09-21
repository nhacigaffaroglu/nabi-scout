from __future__ import annotations

import ast
from pathlib import Path


COMPONENT = Path("components/turkiye_fund_candidate_detail_ui.py")
SERVICE = Path("services/turkiye_fund_candidate_detail.py")


def test_component_uses_shared_review_reason_helper():
    source = COMPONENT.read_text(encoding="utf-8")

    assert (
        "from services.turkiye_fund_review_reason_presentation "
        "import primary_review_reason"
    ) in source
    assert "def _render_review_intelligence(detail) -> None:" in source
    assert source.count("_render_review_intelligence(detail)") == 2
    assert "İnceleme kök nedeni" in source
    assert "primary.family_label" in source
    assert "primary.action" in source


def test_review_intelligence_is_diagnostics_only_and_ready_is_silent():
    source = COMPONENT.read_text(encoding="utf-8")
    block = source.split(
        "def _render_review_intelligence(detail) -> None:", 1
    )[1].split(
        "def render_turkiye_fund_candidate_detail", 1
    )[0]

    assert "if status == 'READY':" in block
    assert "primary_review_reason(row)" in block

    forbidden = (
        "candidate_rank =",
        "candidate_eligible =",
        "recommendation =",
        "place_order",
        "execute_trade",
        "new_money",
        "eight_e",
        "portfolio_write",
        "production_persist = True",
    )
    lowered = block.lower()
    for token in forbidden:
        assert token.lower() not in lowered


def test_review_intelligence_call_is_after_existing_reason_write():
    source = COMPONENT.read_text(encoding="utf-8")
    reason_pos = source.index("st.write(_humanize_reason(detail.reason))")
    call_pos = source.index(
        "_render_review_intelligence(detail)",
        source.index("def render_turkiye_fund_candidate_detail"),
    )
    assert reason_pos < call_pos


def test_candidate_detail_service_has_no_new_review_intelligence_dependency():
    source = SERVICE.read_text(encoding="utf-8")

    assert "primary_review_reason" not in source
    assert "turkiye_fund_review_intelligence" not in source
    assert "turkiye_fund_review_reason_presentation" not in source


def test_component_source_parses_and_render_exists_once():
    source = COMPONENT.read_text(encoding="utf-8")
    tree = ast.parse(source)

    renders = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "render_turkiye_fund_candidate_detail"
    ]
    helpers = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_render_review_intelligence"
    ]
    assert len(renders) == 1
    assert len(helpers) == 1
