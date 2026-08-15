"""Shared Microsoft Graph OAuth2 plumbing for the Outlook/OneDrive/MS Teams
connectors — one Azure AD app registration, one token endpoint, one refresh
flow, reused across all three adapters via mixin (same reasoning as Google
Calendar/Sheets/Drive sharing one Google Cloud project).

Not itself a :class:`ConnectorAdapter` — each connector still subclasses that
and this mixin together, and still defines its own scope/provider/sync.
"""

from __future__ import annotations

from typing import Any

import httpx

from apps.api.services.connectors.base import ConnectorValidationError, OAuthTokenResult
from ekoa_config.settings import get_settings

GRAPH_API = "https://graph.microsoft.com/v1.0"
DEFAULT_TIMEOUT = httpx.Timeout(30.0)


def _token_url() -> str:
    settings = get_settings()
    return f"https://login.microsoftonline.com/{settings.MICROSOFT_TENANT_ID}/oauth2/v2.0/token"


def _authorize_url() -> str:
    settings = get_settings()
    return f"https://login.microsoftonline.com/{settings.MICROSOFT_TENANT_ID}/oauth2/v2.0/authorize"


def graph_request(method: str, url: str, access_token: str, **kwargs: Any) -> httpx.Response:
    headers = {"Authorization": f"Bearer {access_token}"}
    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        return client.request(method, url, headers=headers, **kwargs)


class MicrosoftOAuthMixin:
    """Provides oauth_authorize_url/oauth_exchange_code/refresh_access_token
    for any Microsoft Graph connector. Subclasses set ``graph_scope``."""

    provider: str = ""
    graph_scope: str = ""

    def oauth_authorize_url(self, state: str, *, workspace_id: str) -> str:
        settings = get_settings()
        # offline_access is required to receive a refresh token (Graph access
        # tokens expire in ~1hr, same lifetime class as Google's).
        scope = f"offline_access {self.graph_scope}"
        return (
            f"{_authorize_url()}"
            f"?client_id={settings.MICROSOFT_CLIENT_ID}"
            f"&redirect_uri={settings.MICROSOFT_OAUTH_REDIRECT_URI}"
            "&response_type=code"
            f"&scope={scope}"
            f"&state={state}"
        )

    def oauth_exchange_code(self, code: str) -> OAuthTokenResult:
        settings = get_settings()
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            resp = client.post(
                _token_url(),
                data={
                    "client_id": settings.MICROSOFT_CLIENT_ID,
                    "client_secret": settings.MICROSOFT_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": settings.MICROSOFT_OAUTH_REDIRECT_URI,
                    "grant_type": "authorization_code",
                    "scope": f"offline_access {self.graph_scope}",
                },
            )
        data = resp.json()
        if "access_token" not in data:
            raise ConnectorValidationError(
                f"Microsoft OAuth exchange failed: {data.get('error_description', data.get('error', 'unknown_error'))}"
            )
        return OAuthTokenResult(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_in=data.get("expires_in"),
            config={},
        )

    def refresh_access_token(self, refresh_token: str) -> OAuthTokenResult:
        settings = get_settings()
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            resp = client.post(
                _token_url(),
                data={
                    "client_id": settings.MICROSOFT_CLIENT_ID,
                    "client_secret": settings.MICROSOFT_CLIENT_SECRET,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                    "scope": f"offline_access {self.graph_scope}",
                },
            )
        data = resp.json()
        if "access_token" not in data:
            raise ConnectorValidationError(
                f"Microsoft token refresh failed: {data.get('error_description', data.get('error', 'unknown_error'))}"
            )
        return OAuthTokenResult(
            access_token=data["access_token"],
            # Microsoft DOES rotate refresh tokens on use, unlike Google —
            # always persist the new one when present.
            refresh_token=data.get("refresh_token", refresh_token),
            expires_in=data.get("expires_in"),
        )
