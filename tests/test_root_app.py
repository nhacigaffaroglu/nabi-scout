import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class RootAppReleaseClosureTests(unittest.TestCase):
    def test_root_app_redirects_to_dashboard(self) -> None:
        source = Path("app.py").read_text(encoding="utf-8")
        self.assertIn('st.switch_page("pages/1_Dashboard.py")', source)
        self.assertNotIn("get_dashboard_stats", source)
        self.assertNotIn("v0.3", source)

    def test_stub_placeholder_pages_removed(self) -> None:
        self.assertFalse(Path("pages/5_Haberler.py").exists())
        self.assertFalse(Path("pages/4_Derin_Analiz.py").exists())

    def test_root_app_dependency_chain_without_streamlit_side_effects(self) -> None:
        mock_st = MagicMock()

        with patch.dict(sys.modules, {"streamlit": mock_st}):
            import importlib

            ui_module = importlib.import_module("services.ui")
            with patch.object(
                ui_module,
                "prepare_protected_page",
                return_value=MagicMock(),
            ):
                spec = importlib.util.spec_from_file_location(
                    "root_app",
                    Path("app.py"),
                )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

        mock_st.switch_page.assert_called_once_with("pages/1_Dashboard.py")


class SidebarReleaseClosureTests(unittest.TestCase):
    def test_sidebar_does_not_show_stale_v0_3_label(self) -> None:
        source = Path("services/ui.py").read_text(encoding="utf-8")
        self.assertNotIn("Candidate Intelligence v0.3", source)
        self.assertIn("Research Platform", source)


if __name__ == "__main__":
    unittest.main()
