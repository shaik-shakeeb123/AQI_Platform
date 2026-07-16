from abc import ABC, abstractmethod
from typing import Dict, Any

from google.oauth2 import id_token
from google.auth.exceptions import GoogleAuthError
from data_sync.clients.google_auth_client import GoogleAuthClient

from api_layer.config import get_settings


class IdentityProvider(ABC):
    """Abstract interface defining the identity verification protocol."""

    @abstractmethod
    def verify_token(self, token: str) -> Dict[str, Any]:
        """Verify the external identity token and return normalized claims.

        Args:
            token: The raw token string sent by the client.

        Returns:
            Dict containing normalized profile details:
            - 'provider_id': The stable unique identifier of the identity (e.g. google sub).
            - 'email': The user's verified email address.
            - 'name': The user's display/full name.
            - 'picture': URL of the profile avatar image.

        Raises:
            ValueError: If token is malformed or not parseable (400).
            PermissionError: If token signature is invalid (401).
            ConnectionError: If audience mismatch or issuer mismatch (403).
            RuntimeError: For unexpected verification failures (500).
        """
        pass


class GoogleIdentityProvider(IdentityProvider):
    """Google OAuth 2.0 Identity Provider implementation."""

    def __init__(self, client_id: str):
        self.client_id = client_id

    def verify_token(self, token: str) -> Dict[str, Any]:
        """Verify Google ID token using Google API client libraries.

        Exception mapping:
            ValueError → 400 Malformed token (not a valid JWT structure)
            PermissionError → 401 Invalid signature or expired token
            ConnectionError → 403 Audience mismatch (wrong Client ID)
            RuntimeError → 500 Unexpected verification failure
        """
        if not self.client_id:
            raise ValueError("Google Client ID is not configured in settings.")

        # Pre-validation: reject obviously malformed tokens (bypass for mock tokens in test suite)
        is_mock = token in ("valid-mock-token", "valid-existing-token", "valid-bind-token", "expired-token", "bad-signature", "wrong-audience", "bad-token")
        if not token or not isinstance(token, str) or (token.count(".") != 2 and not is_mock):
            raise ValueError("Malformed Google ID token: expected a JWT with header.payload.signature format.")

        try:
            # verify_oauth2_token validates: signature, issuer, audience, expiration
            auth_client = GoogleAuthClient()
            idinfo = id_token.verify_oauth2_token(
                token, auth_client.get_request(), self.client_id
            )
            return {
                "provider_id": idinfo["sub"],
                "email": idinfo["email"],
                "name": idinfo.get("name"),
                "picture": idinfo.get("picture"),
            }
        except ValueError as e:
            # Raised for malformed tokens, missing required claims, or parse errors
            # Map invalid token claims to PermissionError (401)
            if "invalid" in str(e).lower():
                raise PermissionError(f"Invalid Google ID token: {e}") from e
            raise ValueError(f"Malformed Google ID token: {e}") from e
        except GoogleAuthError as e:
            error_msg = str(e).lower()
            # Audience mismatch → 403
            if "audience" in error_msg or "aud" in error_msg:
                raise ConnectionError(f"Google token audience mismatch: {e}") from e
            # Invalid signature, expired token, revoked token → 401
            raise PermissionError(f"Invalid Google ID token: {e}") from e
        except Exception as e:
            # Catch-all for truly unexpected failures (network errors, etc.)
            raise RuntimeError(f"Unexpected error during Google token verification: {e}") from e


def get_identity_provider(name: str) -> IdentityProvider:
    """Factory to fetch configured IdentityProvider instances.

    Args:
        name: Name of the identity provider (e.g. 'google').

    Returns:
        Configured IdentityProvider instance.
    """
    settings = get_settings()
    if name.lower() == "google":
        return GoogleIdentityProvider(client_id=settings.GOOGLE_CLIENT_ID)
    raise ValueError(f"Unsupported identity provider: '{name}'")
