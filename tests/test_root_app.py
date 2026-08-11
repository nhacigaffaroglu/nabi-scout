import importlib.util
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from repositories.candidate_repository import CandidateRepository

CANONICAL_DASHBOARD_STATS_KEYS = frozenset({
    "total",
    "strong",
    "watch",
    "open_research",
    "incelemde",
    "tekrar_bak",
    "participation_ok",
})

STALE_DASHBOARD_STATS_KEYS = frozenset({"researching"})


class RootAppImportTests(unittest.TestCase):
    def test_get_dashboard_stats_contract(self) -> None:
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.execute.return_value.data = [
            {
                "decision": "GÜÇLÜ ADAY",
                "research_status": "INCELEMEDE",
                "participation_status": "Uygun",
            },
            {
                "decision": "İZLE",
                "research_status": "TAMAMLANDI",
                "participation_status": "Kontrol Et",
            },
        ]
        stats = CandidateRepository(mock_client).get_dashboard_stats()

        self.assertTrue(CANONICAL_DASHBOARD_STATS_KEYS.issubset(stats.keys()))
        self.assertFalse(STALE_DASHBOARD_STATS_KEYS & stats.keys())
        self.assertEqual(stats["open_research"], 1)
        self.assertEqual(stats["incelemde"], 1)

    def test_root_app_does_not_reference_stale_stats_keys(self) -> None:
        source = Path("app.py").read_text(encoding="utf-8")
        referenced = set(re.findall(r"""stats\[['"]([^'"]+)['"]\]""", source))
        unknown = referenced - CANONICAL_DASHBOARD_STATS_KEYS
        stale = referenced & STALE_DASHBOARD_STATS_KEYS

        self.assertFalse(stale, f"app.py still references stale stats keys: {stale}")
        self.assertFalse(
            unknown,
            f"app.py references unknown dashboard stats keys: {unknown}",
        )

    def test_root_app_dependency_chain_without_streamlit_side_effects(self) -> None:
        mock_st = MagicMock()
        mock_st.columns.return_value = [MagicMock() for _ in range(5)]

        mock_repo = MagicMock()
        mock_repo.get_dashboard_stats.return_value = {
            key: 0 for key in CANONICAL_DASHBOARD_STATS_KEYS
        }
        mock_repo.get_all.return_value = []

        with patch.dict(sys.modules, {"streamlit": mock_st}):
            with patch("services.supabase_client.get_supabase_client") as mock_client:
                mock_client.return_value = MagicMock()
                with patch(
                    "repositories.candidate_repository.CandidateRepository",
                    return_value=mock_repo,
                ):
                    spec = importlib.util.spec_from_file_location(
                        "root_app",
                        Path("app.py"),
                    )
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)

        mock_repo.get_dashboard_stats.assert_called_once()
        mock_st.title.assert_called_with("🔭 NABI Scout")


if __name__ == "__main__":
    unittest.main()
