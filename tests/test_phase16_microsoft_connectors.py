"""Phase 16 Part A-3 tests: Outlook, OneDrive, MS Teams adapters (Microsoft
Graph OAuth2, one shared Azure AD app).

Same mocked-single-seam pattern as tests/test_phase14.py — live end-to-end
verification against the real service happens separately.
"""

from __future__ import annotations

import httpx
import pytest

from apps.api.services.connectors.base import ConnectorValidationError, get_connector_adapter
from apps.api.services.connectors.outlook import OutlookConnector
from apps.api.services.connectors.onedrive import OneDriveConnector
from apps.api.services.connectors.ms_teams import MsTeamsConnector


def _resp(status_code: int, json_body: dict) -> httpx.Response:
    return httpx.Response(status_code, json=json_body, request=httpx.Request("GET", "http://x"))


def test_registry_resolves_microsoft_connectors():
    assert isinstance(get_connector_adapter("outlook"), OutlookConnector)
    assert isinstance(get_connector_adapter("onedrive"), OneDriveConnector)
    assert isinstance(get_connector_adapter("ms_teams"), MsTeamsConnector)


# ── Shared OAuth plumbing ────────────────────────────────────────────────────


def test_outlook_authorize_url_uses_tenant_and_scope(monkeypatch):
    from ekoa_config.settings import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "MICROSOFT_CLIENT_ID", "test-client")
    monkeypatch.setattr(settings, "MICROSOFT_TENANT_ID", "test-tenant")
    monkeypatch.setattr(
        settings, "MICROSOFT_OAUTH_REDIRECT_URI",
        "http://localhost/api/v1/connectors/oauth/microsoft/callback",
    )
    url = OutlookConnector().oauth_authorize_url("state123", workspace_id="ws-1")
    assert "login.microsoftonline.com/test-tenant" in url
    assert "Mail.Read" in url
    assert "offline_access" in url
    assert "microsoft/callback" in url


def test_onedrive_authorize_url_uses_files_scope(monkeypatch):
    from ekoa_config.settings import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "MICROSOFT_CLIENT_ID", "test-client")
    url = OneDriveConnector().oauth_authorize_url("state123", workspace_id="ws-1")
    assert "Files.Read.All" in url


def test_ms_teams_authorize_url_uses_team_and_channel_scopes(monkeypatch):
    from ekoa_config.settings import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "MICROSOFT_CLIENT_ID", "test-client")
    url = MsTeamsConnector().oauth_authorize_url("state123", workspace_id="ws-1")
    assert "Team.ReadBasic.All" in url
    assert "Channel.ReadBasic.All" in url


def test_oauth_exchange_code_success(monkeypatch):
    def fake_post(self, url, data=None, **kwargs):
        return _resp(200, {"access_token": "tok", "refresh_token": "rtok", "expires_in": 3600})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = OutlookConnector().oauth_exchange_code("code123")
    assert result.access_token == "tok"
    assert result.refresh_token == "rtok"
    assert result.expires_in == 3600


def test_oauth_exchange_code_rejects_bad_code(monkeypatch):
    def fake_post(self, url, data=None, **kwargs):
        return _resp(400, {"error": "invalid_grant", "error_description": "bad code"})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    with pytest.raises(ConnectorValidationError):
        OutlookConnector().oauth_exchange_code("bad-code")


def test_refresh_access_token_rotates_refresh_token(monkeypatch):
    def fake_post(self, url, data=None, **kwargs):
        return _resp(200, {"access_token": "new-tok", "refresh_token": "new-rtok", "expires_in": 3600})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = OneDriveConnector().refresh_access_token("old-rtok")
    assert result.access_token == "new-tok"
    assert result.refresh_token == "new-rtok"


def test_refresh_access_token_keeps_old_token_if_not_rotated(monkeypatch):
    def fake_post(self, url, data=None, **kwargs):
        return _resp(200, {"access_token": "new-tok", "expires_in": 3600})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = OneDriveConnector().refresh_access_token("old-rtok")
    assert result.refresh_token == "old-rtok"


# ── Outlook ──────────────────────────────────────────────────────────────────


def test_outlook_test_connection_success(monkeypatch):
    monkeypatch.setattr(
        "apps.api.services.connectors.outlook.graph_request",
        lambda *a, **k: _resp(200, {"mail": "me@example.com"}),
    )
    result = OutlookConnector().test_connection({}, "token")
    assert result["account"] == "me@example.com"


def test_outlook_test_connection_rejects_expired_token(monkeypatch):
    monkeypatch.setattr(
        "apps.api.services.connectors.outlook.graph_request",
        lambda *a, **k: _resp(401, {}),
    )
    with pytest.raises(ConnectorValidationError):
        OutlookConnector().test_connection({}, "expired")


# ── OneDrive ─────────────────────────────────────────────────────────────────


def test_onedrive_test_connection_success(monkeypatch):
    monkeypatch.setattr(
        "apps.api.services.connectors.onedrive.graph_request",
        lambda *a, **k: _resp(200, {"userPrincipalName": "me@example.com"}),
    )
    result = OneDriveConnector().test_connection({}, "token")
    assert result["account"] == "me@example.com"


# ── MS Teams ─────────────────────────────────────────────────────────────────


def test_ms_teams_test_connection_success(monkeypatch):
    monkeypatch.setattr(
        "apps.api.services.connectors.ms_teams.graph_request",
        lambda *a, **k: _resp(200, {"mail": "me@example.com"}),
    )
    result = MsTeamsConnector().test_connection({}, "token")
    assert result["account"] == "me@example.com"


def test_ms_teams_test_connection_rejects_bad_token(monkeypatch):
    monkeypatch.setattr(
        "apps.api.services.connectors.ms_teams.graph_request",
        lambda *a, **k: _resp(401, {}),
    )
    with pytest.raises(ConnectorValidationError):
        MsTeamsConnector().test_connection({}, "bad")
