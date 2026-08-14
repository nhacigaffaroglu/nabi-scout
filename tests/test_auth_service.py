from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.auth_dev_config import DevAuthConfig, load_dev_auth_config
from services.auth_service import (
    AUTH_FAILURE_MESSAGE,
    DEV_AUTH_CONFIG_MESSAGE,
    LOGIN_FAILURE_MESSAGE,
    SESSION_ACCESS_TOKEN_KEY,
    SESSION_REFRESH_TOKEN_KEY,
    SESSION_USER_EMAIL_KEY,
    apply_session_to_client,
    clear_auth_session,
    get_current_user_id,
    is_authenticated,
    require_authentication,
    sign_in_with_password,
    sign_out,
)
from services.supabase_client import AuthenticationRequired


class AuthSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session_state: dict = {}
        self.mock_st = MagicMock()
        self.mock_st.session_state = self.session_state
        self.mock_st.stop.side_effect = RuntimeError("stop")
        self.st_patch = patch("services.auth_service.st", self.mock_st)
        self.st_patch.start()

    def tearDown(self) -> None:
        self.st_patch.stop()

    def test_is_authenticated_false_when_tokens_missing(self) -> None:
        self.assertFalse(is_authenticated())

    def test_is_authenticated_true_when_tokens_present(self) -> None:
        self.session_state[SESSION_ACCESS_TOKEN_KEY] = "access"
        self.session_state[SESSION_REFRESH_TOKEN_KEY] = "refresh"
        self.assertTrue(is_authenticated())

    def test_clear_auth_session_removes_keys(self) -> None:
        self.session_state[SESSION_ACCESS_TOKEN_KEY] = "access"
        self.session_state[SESSION_REFRESH_TOKEN_KEY] = "refresh"
        self.session_state[SESSION_USER_EMAIL_KEY] = "user@example.com"
        self.session_state["adviser_chat_user-1_portfolio-1"] = [{"role": "user", "content": "hi"}]
        self.session_state["adviser_response_user-1_portfolio-1"] = {"answer": "x"}
        clear_auth_session()
        self.assertEqual(self.session_state, {})

    def test_get_supabase_client_fail_closed_without_session(self) -> None:
        from services.supabase_client import get_supabase_client

        mock_st = MagicMock()
        mock_st.session_state = {}
        with patch("services.auth_service.st", mock_st):
            with self.assertRaises(AuthenticationRequired):
                get_supabase_client()

    def test_apply_session_to_client_requires_tokens(self) -> None:
        client = MagicMock()
        with self.assertRaises(AuthenticationRequired):
            apply_session_to_client(client)

    def test_apply_session_to_client_sets_supabase_session(self) -> None:
        self.session_state[SESSION_ACCESS_TOKEN_KEY] = "access-token"
        self.session_state[SESSION_REFRESH_TOKEN_KEY] = "refresh-token"
        client = MagicMock()
        apply_session_to_client(client)
        client.auth.set_session.assert_called_once_with(
            "access-token",
            "refresh-token",
        )

    def test_sign_in_with_password_stores_session(self) -> None:
        mock_client = MagicMock()
        mock_session = MagicMock(access_token="access", refresh_token="refresh")
        mock_client.auth.sign_in_with_password.return_value = MagicMock(
            session=mock_session,
        )
        with patch(
            "services.auth_service.get_supabase_client_for_auth",
            return_value=mock_client,
        ):
            sign_in_with_password("user@example.com", "secret")
        self.assertEqual(self.session_state[SESSION_ACCESS_TOKEN_KEY], "access")
        self.assertEqual(self.session_state[SESSION_REFRESH_TOKEN_KEY], "refresh")
        self.assertEqual(self.session_state[SESSION_USER_EMAIL_KEY], "user@example.com")

    def test_sign_in_without_session_raises(self) -> None:
        mock_client = MagicMock()
        mock_client.auth.sign_in_with_password.return_value = MagicMock(session=None)
        with patch(
            "services.auth_service.get_supabase_client_for_auth",
            return_value=mock_client,
        ):
            with self.assertRaises(AuthenticationRequired):
                sign_in_with_password("user@example.com", "secret")

    def test_sign_out_clears_session_even_when_provider_fails(self) -> None:
        self.session_state[SESSION_ACCESS_TOKEN_KEY] = "access"
        self.session_state[SESSION_REFRESH_TOKEN_KEY] = "refresh"
        mock_client = MagicMock()
        mock_client.auth.sign_out.side_effect = RuntimeError("network")
        with patch(
            "services.auth_service.get_supabase_client_for_auth",
            return_value=mock_client,
        ):
            sign_out()
        self.assertFalse(is_authenticated())

    def test_require_authentication_stops_when_unauthenticated(self) -> None:
        with patch("services.auth_service.load_dev_auth_config", return_value=DevAuthConfig(False, None, None)):
            with self.assertRaises(RuntimeError):
                require_authentication()
        self.mock_st.stop.assert_called()

    def test_require_authentication_returns_client_when_valid(self) -> None:
        self.session_state[SESSION_ACCESS_TOKEN_KEY] = "access"
        self.session_state[SESSION_REFRESH_TOKEN_KEY] = "refresh"
        mock_client = MagicMock()
        mock_client.auth.get_user.return_value = MagicMock(user=MagicMock())
        with patch(
            "services.auth_service.get_supabase_client",
            return_value=mock_client,
        ):
            client = require_authentication()
        self.assertIs(client, mock_client)

    def test_require_authentication_fail_closed_on_invalid_session(self) -> None:
        self.session_state[SESSION_ACCESS_TOKEN_KEY] = "access"
        self.session_state[SESSION_REFRESH_TOKEN_KEY] = "refresh"
        mock_client = MagicMock()
        mock_client.auth.get_user.side_effect = RuntimeError("expired")
        with patch(
            "services.auth_service.get_supabase_client",
            return_value=mock_client,
        ):
            with self.assertRaises(RuntimeError):
                require_authentication()
        self.assertFalse(is_authenticated())
        self.mock_st.error.assert_called_with(AUTH_FAILURE_MESSAGE)

    def test_login_failure_message_is_generic(self) -> None:
        self.assertIn("Giriş başarısız", LOGIN_FAILURE_MESSAGE)

    def test_get_current_user_id_reads_supabase_user(self) -> None:
        mock_client = MagicMock()
        mock_client.auth.get_user.return_value = MagicMock(user=MagicMock(id="user-123"))
        self.assertEqual(get_current_user_id(mock_client), "user-123")


class DevAutoLoginTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session_state: dict = {}
        self.mock_st = MagicMock()
        self.mock_st.session_state = self.session_state
        self.mock_st.stop.side_effect = RuntimeError("stop")
        self.st_patch = patch("services.auth_service.st", self.mock_st)
        self.st_patch.start()

    def tearDown(self) -> None:
        self.st_patch.stop()

    def test_dev_auto_login_disabled_shows_login_gate(self) -> None:
        with patch(
            "services.auth_service.load_dev_auth_config",
            return_value=DevAuthConfig(False, None, None),
        ):
            with self.assertRaises(RuntimeError):
                require_authentication()
        self.mock_st.title.assert_called()

    def test_dev_auto_login_enabled_establishes_session(self) -> None:
        mock_client = MagicMock()
        mock_client.auth.get_user.return_value = MagicMock(user=MagicMock())
        mock_session = MagicMock(access_token="access", refresh_token="refresh")
        with patch(
            "services.auth_service.load_dev_auth_config",
            return_value=DevAuthConfig(True, "dev@example.com", "secret"),
        ), patch(
            "services.auth_service.get_supabase_client_for_auth",
        ) as auth_client_factory, patch(
            "services.auth_service.get_supabase_client",
            return_value=mock_client,
        ):
            auth_client = MagicMock()
            auth_client.auth.sign_in_with_password.return_value = MagicMock(session=mock_session)
            auth_client_factory.return_value = auth_client
            client = require_authentication()
        self.assertIs(client, mock_client)
        self.assertTrue(is_authenticated())
        auth_client.auth.sign_in_with_password.assert_called_once_with(
            {"email": "dev@example.com", "password": "secret"},
        )

    def test_dev_auto_login_missing_credentials_fail_closed(self) -> None:
        with patch(
            "services.auth_service.load_dev_auth_config",
            return_value=DevAuthConfig(True, "", ""),
        ):
            with self.assertRaises(RuntimeError):
                require_authentication()
        self.mock_st.error.assert_called()
        self.assertIn(DEV_AUTH_CONFIG_MESSAGE, self.mock_st.error.call_args.args[0])

    def test_dev_auto_login_bad_credentials_fail_closed(self) -> None:
        with patch(
            "services.auth_service.load_dev_auth_config",
            return_value=DevAuthConfig(True, "dev@example.com", "bad"),
        ), patch(
            "services.auth_service.get_supabase_client_for_auth",
        ) as auth_client_factory:
            auth_client = MagicMock()
            auth_client.auth.sign_in_with_password.side_effect = RuntimeError("invalid")
            auth_client_factory.return_value = auth_client
            with self.assertRaises(RuntimeError):
                require_authentication()
        self.assertFalse(is_authenticated())
        self.assertIn(DEV_AUTH_CONFIG_MESSAGE, self.mock_st.error.call_args.args[0])

    def test_dev_config_error_messages_never_include_password(self) -> None:
        with patch(
            "services.auth_service.load_dev_auth_config",
            return_value=DevAuthConfig(True, "dev@example.com", "super-secret-password"),
        ), patch(
            "services.auth_service.get_supabase_client_for_auth",
        ) as auth_client_factory:
            auth_client = MagicMock()
            auth_client.auth.sign_in_with_password.side_effect = RuntimeError("invalid")
            auth_client_factory.return_value = auth_client
            with self.assertRaises(RuntimeError):
                require_authentication()
        error_message = self.mock_st.error.call_args.args[0]
        self.assertNotIn("super-secret-password", error_message)

    def test_load_dev_auth_config_prefers_environment(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "NABI_DEV_AUTO_LOGIN": "true",
                "NABI_DEV_USER_EMAIL": "env@example.com",
                "NABI_DEV_USER_PASSWORD": "env-secret",
            },
            clear=False,
        ), patch("services.auth_dev_config._load_dev_auth_from_secrets", return_value=(False, None, None)):
            config = load_dev_auth_config()
        self.assertTrue(config.enabled)
        self.assertEqual(config.email, "env@example.com")
        self.assertEqual(config.password, "env-secret")


class AuthSecurityTests(unittest.TestCase):
    def test_no_service_role_in_auth_layer(self) -> None:
        for relative_path in (
            "services/auth_service.py",
            "services/auth_dev_config.py",
            "services/supabase_client.py",
        ):
            source = Path(relative_path).read_text(encoding="utf-8").lower()
            self.assertNotIn("service_role", source, relative_path)

    def test_browser_cookie_persistence_removed(self) -> None:
        self.assertFalse(Path("services/auth_browser_persistence.py").exists())
        auth_source = Path("services/auth_service.py").read_text(encoding="utf-8")
        self.assertNotIn("auth_browser_persistence", auth_source)
        self.assertNotIn("nabi_auth_rt", auth_source)

    def test_phase3_logout_cleanup_preserved(self) -> None:
        source = Path("services/auth_service.py").read_text(encoding="utf-8")
        self.assertIn("clear_adviser_session_state", source)

    def test_adviser_prompt_has_no_dev_credentials(self) -> None:
        source = Path("services/wealth_adviser_prompt.py").read_text(encoding="utf-8").lower()
        self.assertNotIn("nabi_dev_user_password", source)
        self.assertNotIn("dev_auth", source)

    def test_logout_hidden_when_dev_auto_login_enabled(self) -> None:
        source = Path("services/ui.py").read_text(encoding="utf-8")
        self.assertIn("is_dev_auto_login_enabled", source)
        self.assertIn("Geliştirme oturumu: otomatik giriş etkin.", source)


class AuthUiIntegrationTests(unittest.TestCase):
    def test_prepare_protected_page_wires_auth_gate(self) -> None:
        source = Path("services/ui.py").read_text(encoding="utf-8")
        self.assertIn("def prepare_protected_page", source)
        self.assertIn("return require_authentication()", source)

    def test_active_pages_use_prepare_protected_page(self) -> None:
        protected_pages = [
            "app.py",
            "pages/1_Dashboard.py",
            "pages/2_Scout_Tarama.py",
            "pages/2_Aday_Havuzu.py",
            "pages/2_Evren_Motoru.py",
            "pages/3_Research_Monitor.py",
            "pages/4_Company_Report.py",
            "pages/4_Aday_Detayi.py",
            "pages/6_Izleme_Listesi.py",
            "pages/7_Ayarlar.py",
            "pages/8_NABI_Akademi.py",
            "pages/9_Fund_Report.py",
        ]
        for relative_path in protected_pages:
            with self.subTest(page=relative_path):
                source = Path(relative_path).read_text(encoding="utf-8")
                self.assertIn(
                    "prepare_protected_page",
                    source,
                    f"{relative_path} must use prepare_protected_page",
                )

    def test_participation_firewall_files_untouched_by_auth_layer(self) -> None:
        auth_source = Path("services/auth_service.py").read_text(encoding="utf-8")
        self.assertNotIn("participation", auth_source.lower())
        self.assertNotIn("nabi_score", auth_source.lower())
        nabi_source = Path("services/nabi_score_v4.py").read_text(encoding="utf-8")
        self.assertIn("Phase 6B.0 firewall", nabi_source)

    def test_supabase_client_not_shared_via_cache_resource(self) -> None:
        source = Path("services/supabase_client.py").read_text(encoding="utf-8")
        self.assertNotIn("@st.cache_resource", source)
        self.assertIn("def _create_supabase_client", source)
        self.assertIn("return _create_supabase_client()", source)


class AuthRlsMigrationTests(unittest.TestCase):
    MIGRATION_PATH = Path("database/migration_auth_rls_hardening.sql")

    ACTIVE_TABLES = (
        "investment_candidates",
        "deep_analyses",
        "news_items",
        "watchlist",
        "scan_runs",
        "scan_results",
        "universe_runs",
        "universe_symbols",
        "tracked_funds",
        "participation_assessment_snapshots",
    )

    def test_migration_exists(self) -> None:
        self.assertTrue(self.MIGRATION_PATH.is_file())

    def test_migration_drops_all_temporary_anon_policies(self) -> None:
        sql = self.MIGRATION_PATH.read_text(encoding="utf-8")
        anon_drops = re.findall(
            r'drop policy if exists "temporary anon[^"]+"',
            sql,
            flags=re.IGNORECASE,
        )
        self.assertEqual(len(anon_drops), len(self.ACTIVE_TABLES))

    def test_migration_has_no_temporary_anon_create(self) -> None:
        sql = self.MIGRATION_PATH.read_text(encoding="utf-8").lower()
        self.assertNotIn('create policy "temporary anon', sql)

    def test_migration_covers_active_tables(self) -> None:
        sql = self.MIGRATION_PATH.read_text(encoding="utf-8")
        for table in self.ACTIVE_TABLES:
            with self.subTest(table=table):
                self.assertIn(f"on public.{table}", sql)

    def test_migration_grants_authenticated_access_per_table(self) -> None:
        sql = self.MIGRATION_PATH.read_text(encoding="utf-8")
        authenticated_policies = re.findall(
            r'create policy "[^"]+"\s*\n\s*on public\.([^\s]+)[\s\S]*?to authenticated',
            sql,
        )
        self.assertEqual(set(authenticated_policies), set(self.ACTIVE_TABLES))

    def test_migration_does_not_alter_schema(self) -> None:
        sql_lines = [
            line.strip().lower()
            for line in self.MIGRATION_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("--")
        ]
        joined = "\n".join(sql_lines)
        self.assertNotIn("alter table", joined)
        self.assertNotIn("drop table", joined)
        self.assertNotIn("delete from", joined)

    def test_migration_notifies_postgrest(self) -> None:
        sql = self.MIGRATION_PATH.read_text(encoding="utf-8")
        self.assertIn("notify pgrst, 'reload schema'", sql)


if __name__ == "__main__":
    unittest.main()
