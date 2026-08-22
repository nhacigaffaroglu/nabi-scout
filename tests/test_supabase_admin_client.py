from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from services.supabase_admin_client import (
    RLS_ADMIN_REQUIRED_MESSAGE,
    SupabaseAdminClientError,
    apply_local_secrets_to_env,
    create_admin_supabase_client,
    is_publishable_supabase_key,
    is_rls_permission_error,
    raise_friendly_rls_error,
)


class PublishableKeyDetectionTests(unittest.TestCase):
    def test_publishable_prefix_detected(self) -> None:
        self.assertTrue(is_publishable_supabase_key("sb_publishable_abc"))
        self.assertFalse(is_publishable_supabase_key("sb_secret_abc"))
        self.assertFalse(is_publishable_supabase_key("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"))


class RlsErrorDetectionTests(unittest.TestCase):
    def test_detects_code_42501(self) -> None:
        exc = Exception("blocked")
        exc.code = "42501"
        self.assertTrue(is_rls_permission_error(exc))

    def test_detects_message(self) -> None:
        self.assertTrue(
            is_rls_permission_error(
                RuntimeError("new row violates row-level security policy")
            )
        )

    def test_raise_friendly_rls_error(self) -> None:
        exc = Exception("row-level security")
        exc.code = "42501"
        with self.assertRaises(SupabaseAdminClientError) as ctx:
            raise_friendly_rls_error(exc)
        self.assertIn("publishable key cannot bypass RLS", str(ctx.exception))
        self.assertNotIn("sb_publishable", str(ctx.exception).lower())


class AdminClientCreationTests(unittest.TestCase):
    def test_publishable_without_auth_cannot_seed(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_KEY": "sb_publishable_test",
            },
            clear=True,
        ), patch(
            "services.supabase_admin_client.load_local_secrets_toml",
            return_value={},
        ), patch(
            "services.supabase_admin_client.load_dev_auth_config",
            return_value=__import__(
                "services.auth_dev_config", fromlist=["DevAuthConfig"]
            ).DevAuthConfig(enabled=False, email=None, password=None),
        ):
            with self.assertRaises(SupabaseAdminClientError) as ctx:
                create_admin_supabase_client()
        self.assertIn("publishable key cannot bypass RLS", str(ctx.exception))

    def test_service_role_path_can_seed(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_SERVICE_ROLE_KEY": "sb_secret_test",
            },
            clear=True,
        ), patch("services.supabase_admin_client.create_client") as mock_create:
            mock_create.return_value = MagicMock()
            client = create_admin_supabase_client()
            self.assertIsNotNone(client)
            mock_create.assert_called_once_with(
                "https://example.supabase.co",
                "sb_secret_test",
            )

    def test_authenticated_dev_auth_path_can_seed(self) -> None:
        secrets = {
            "supabase": {
                "url": "https://example.supabase.co",
                "publishable_key": "sb_publishable_test",
            },
            "dev_auth": {
                "enabled": "true",
                "email": "admin@example.com",
                "password": "secret-password",
            },
        }
        mock_client = MagicMock()
        mock_session = MagicMock(access_token="jwt-token")
        mock_client.auth.sign_in_with_password.return_value = MagicMock(
            session=mock_session
        )
        with patch.dict("os.environ", {}, clear=True), patch(
            "services.supabase_admin_client.load_local_secrets_toml",
            return_value=secrets,
        ), patch(
            "services.supabase_admin_client.create_client",
            return_value=mock_client,
        ):
            client = create_admin_supabase_client()
        self.assertIs(client, mock_client)
        mock_client.postgrest.auth.assert_called_once_with("jwt-token")

    def test_no_secret_values_in_error_messages(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_KEY": "sb_publishable_leaked-value",
            },
            clear=True,
        ), patch(
            "services.supabase_admin_client.load_local_secrets_toml",
            return_value={},
        ), patch(
            "services.supabase_admin_client.load_dev_auth_config",
            return_value=__import__(
                "services.auth_dev_config", fromlist=["DevAuthConfig"]
            ).DevAuthConfig(enabled=False, email=None, password=None),
        ):
            with self.assertRaises(SupabaseAdminClientError) as ctx:
                create_admin_supabase_client()
        message = str(ctx.exception).lower()
        self.assertNotIn("leaked-value", message)
        self.assertNotIn("password", message)


class LocalSecretsLoaderTests(unittest.TestCase):
    def test_apply_local_secrets_sets_missing_env_names_only(self) -> None:
        with patch.dict("os.environ", {}, clear=True), patch(
            "services.supabase_admin_client.load_local_secrets_toml",
            return_value={
                "supabase": {
                    "url": "https://example.supabase.co",
                    "publishable_key": "sb_publishable_x",
                },
                "fmp": {"api_key": "fmp-key"},
                "alpha_vantage": {"api_key": "av-key"},
                "twelve_data": {"api_key": "td-key"},
                "sec": {"contact_email": "sec@example.com"},
            },
        ):
            apply_local_secrets_to_env()
            self.assertEqual(os.environ["SUPABASE_URL"], "https://example.supabase.co")
            self.assertEqual(os.environ["SUPABASE_PUBLISHABLE_KEY"], "sb_publishable_x")
            self.assertEqual(os.environ["FMP_API_KEY"], "fmp-key")
            self.assertEqual(os.environ["ALPHA_VANTAGE_API_KEY"], "av-key")
            self.assertEqual(os.environ["TWELVE_DATA_API_KEY"], "td-key")
            self.assertEqual(os.environ["SEC_CONTACT_EMAIL"], "sec@example.com")


if __name__ == "__main__":
    unittest.main()
