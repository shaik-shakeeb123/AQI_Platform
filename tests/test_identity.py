"""Unit and integration tests for identity provider and Google OAuth settings lifecycle."""

import hashlib
import os
from unittest.mock import patch, MagicMock

import pytest
from google.auth.exceptions import GoogleAuthError

from api_layer.config import get_settings, clear_settings_cache
from services.identity import GoogleIdentityProvider, get_identity_provider


class TestIdentitySettingsLifecycle:
    """Verifies dynamic settings loading, memoization, and cache clearing."""

    def test_settings_memoization(self):
        """get_settings() should return the same singleton instance due to lru_cache."""
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_clear_settings_cache(self):
        """clear_settings_cache() must invalidate the lru_cache so a new instance is created."""
        s1 = get_settings()
        clear_settings_cache()
        s2 = get_settings()
        assert s1 is not s2

    def test_dynamic_google_client_id_via_environ(self):
        """When GOOGLE_CLIENT_ID is updated in os.environ and cache is cleared,
        get_identity_provider must supply the new client_id immediately.
        """
        original_env = os.environ.get("GOOGLE_CLIENT_ID")
        mock_id = "test-new-client-id-12345.apps.googleusercontent.com"
        try:
            os.environ["GOOGLE_CLIENT_ID"] = mock_id
            clear_settings_cache()

            provider = get_identity_provider("google")
            assert isinstance(provider, GoogleIdentityProvider)
            assert provider.client_id == mock_id
        finally:
            if original_env is not None:
                os.environ["GOOGLE_CLIENT_ID"] = original_env
            else:
                os.environ.pop("GOOGLE_CLIENT_ID", None)
            clear_settings_cache()

    def test_get_identity_provider_unsupported(self):
        """Requesting an unsupported provider name must raise ValueError."""
        with pytest.raises(ValueError, match="Unsupported identity provider: 'github'"):
            get_identity_provider("github")


class TestGoogleIdentityProviderVerification:
    """Verifies token verification behavior, error classifications, and audience validation."""

    def test_missing_client_id_raises_value_error(self):
        provider = GoogleIdentityProvider(client_id="")
        with pytest.raises(ValueError, match="Google Client ID is not configured"):
            provider.verify_token("any.mock.jwt")

    def test_malformed_token_raises_value_error(self):
        provider = GoogleIdentityProvider(client_id="test-client-id")
        with pytest.raises(ValueError, match="Malformed Google ID token"):
            provider.verify_token("not-a-jwt")

    @patch("services.identity.id_token.verify_oauth2_token")
    @patch("services.identity.GoogleAuthClient")
    def test_successful_token_verification(self, mock_auth_client_cls, mock_verify):
        mock_verify.return_value = {
            "sub": "google-user-12345",
            "email": "user@example.com",
            "name": "Test User",
            "picture": "https://example.com/avatar.png",
        }
        provider = GoogleIdentityProvider(client_id="expected-client-id")
        claims = provider.verify_token("header.payload.signature")

        assert claims["provider_id"] == "google-user-12345"
        assert claims["email"] == "user@example.com"
        assert claims["name"] == "Test User"
        assert claims["picture"] == "https://example.com/avatar.png"

    @patch("services.identity.id_token.verify_oauth2_token")
    @patch("services.identity.GoogleAuthClient")
    def test_audience_mismatch_raises_connection_error_403(self, mock_auth_client_cls, mock_verify):
        """Simulates Google throwing audience mismatch (Token used with wrong audience).
        Must be mapped to ConnectionError (which route translates to HTTP 403).
        """
        mock_verify.side_effect = GoogleAuthError(
            "Token used with wrong audience: 561174262810-4fvv1hd22o5r7rqojisntfmrgokv3cm2.apps.googleusercontent.com"
        )
        provider = GoogleIdentityProvider(client_id="561174262810-rd83kmg1ag04q1o63uuu2mnko3n4v04c.apps.googleusercontent.com")

        with pytest.raises(ConnectionError, match="Google token audience mismatch"):
            provider.verify_token("header.payload.signature")

    @patch("services.identity.id_token.verify_oauth2_token")
    @patch("services.identity.GoogleAuthClient")
    def test_signature_expired_raises_permission_error_401(self, mock_auth_client_cls, mock_verify):
        mock_verify.side_effect = GoogleAuthError("Token signature has expired")
        provider = GoogleIdentityProvider(client_id="expected-client-id")

        with pytest.raises(PermissionError, match="Invalid Google ID token"):
            provider.verify_token("header.payload.signature")


class TestStartupDiagnosticLogging:
    """Verifies that the startup diagnostic line formats safely without exposing credentials."""

    @pytest.mark.asyncio
    async def test_startup_log_emits_expected_diagnostics(self):
        from api_layer.main import app, lifespan

        with patch("api_layer.main.logger.info") as mock_info:
            async with lifespan(app):
                pass

        diag_calls = [
            c for c in mock_info.call_args_list
            if len(c[0]) > 0 and "[Startup Configuration]" in str(c[0][0])
        ]
        assert len(diag_calls) == 1
        fmt_str, *args = diag_calls[0][0]
        assert "[Startup Configuration] GOOGLE_CLIENT_ID configured:" in fmt_str
        assert args[0] is True  # configured
        assert args[1] == 72    # length of configured client ID
        assert len(args[2]) == 64  # sha256 hash length
        assert args[3] is True  # matches_expected
        assert args[4] in (".env file", "os.environ")  # source
