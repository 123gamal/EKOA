"""Phase 16 Part A tests: Google Calendar, Google Sheets, Confluence adapters.

Same mocked-single-seam pattern as tests/test_phase14.py. Live end-to-end
verification against the real services happens separately (this session's
live verification), not as part of the automated suite.
"""

from __future__ import annotations

import httpx
import pytest

from apps.api.services.connectors.base import ConnectorValidationError, get_connector_adapter
from apps.api.services.connectors.google_calendar import GoogleCalendarConnector
from apps.api.services.connectors.google_sheets import GoogleSheetsConnector
from apps.api.services.connectors.confluence import ConfluenceConnector


def _resp(status_code: int, json_body: dict) -> httpx.Response:
    return httpx.Response(status_code, json=json_body, request=httpx.Request("GET", "http://x"))


def test_registry_resolves_phase16_connectors():
    assert isinstance(get_connector_adapter("google_calendar"), GoogleCalendarConnector)
    assert isinstance(get_connector_adapter("google_sheets"), GoogleSheetsConnector)
    assert isinstance(get_connector_adapter("confluence"), ConfluenceConnector)


# ── Google Calendar ──────────────────────────────────────────────────────────


def test_google_calendar_test_connection_success(monkeypatch):
    monkeypatch.setattr(
        "apps.api.services.connectors.google_calendar._calendar_request",
        lambda *a, **k: _resp(200, {"id": "me@example.com"}),
    )
    result = GoogleCalendarConnector().test_connection({}, "ya29.fake")
    assert result["account"] == "me@example.com"


def test_google_calendar_rejects_expired_token(monkeypatch):
    monkeypatch.setattr(
        "apps.api.services.connectors.google_calendar._calendar_request",
        lambda *a, **k: _resp(401, {}),
    )
    with pytest.raises(ConnectorValidationError):
        GoogleCalendarConnector().test_connection({}, "ya29.expired")


def test_google_calendar_authorize_url_uses_own_redirect_uri(monkeypatch):
    from ekoa_config import settings as settings_mod

    settings = settings_mod.get_settings()
    monkeypatch.setattr(settings, "GOOGLE_DRIVE_CLIENT_ID", "test-client")
    monkeypatch.setattr(
        settings, "GOOGLE_CALENDAR_OAUTH_REDIRECT_URI",
        "http://localhost/api/v1/connectors/oauth/google_calendar/callback",
    )
    url = GoogleCalendarConnector().oauth_authorize_url("state123", workspace_id="ws-1")
    assert "google_calendar/callback" in url
    assert "calendar.readonly" in url


# ── Google Sheets ────────────────────────────────────────────────────────────


def test_google_sheets_test_connection_success(monkeypatch):
    monkeypatch.setattr(
        "apps.api.services.connectors.google_sheets._sheets_request",
        lambda *a, **k: _resp(200, {"user": {"emailAddress": "me@example.com"}}),
    )
    result = GoogleSheetsConnector().test_connection({}, "ya29.fake")
    assert result["account"] == "me@example.com"


def test_google_sheets_authorize_url_requests_both_scopes(monkeypatch):
    from ekoa_config import settings as settings_mod

    settings = settings_mod.get_settings()
    monkeypatch.setattr(settings, "GOOGLE_DRIVE_CLIENT_ID", "test-client")
    url = GoogleSheetsConnector().oauth_authorize_url("state123", workspace_id="ws-1")
    assert "spreadsheets.readonly" in url
    assert "drive.readonly" in url


# ── Confluence ───────────────────────────────────────────────────────────────


def test_confluence_split_credential_requires_colon():
    with pytest.raises(ConnectorValidationError):
        ConfluenceConnector._split_credential("no-colon-here")
    email, token = ConfluenceConnector._split_credential("a@b.com:sometoken")
    assert email == "a@b.com" and token == "sometoken"


def test_confluence_test_connection_success(monkeypatch):
    monkeypatch.setattr(
        "apps.api.services.connectors.confluence._confluence_request",
        lambda *a, **k: _resp(200, {"name": "Engineering Space"}),
    )
    adapter = ConfluenceConnector()
    result = adapter.test_connection(
        {"base_url": "https://x.atlassian.net", "space_key": "eng"}, "a@b.com:tok"
    )
    assert result["space_key"] == "ENG"
    assert result["space_name"] == "Engineering Space"
    assert adapter.identity_key(result) == "eng"


def test_confluence_test_connection_rejects_bad_token(monkeypatch):
    monkeypatch.setattr(
        "apps.api.services.connectors.confluence._confluence_request",
        lambda *a, **k: _resp(401, {}),
    )
    with pytest.raises(ConnectorValidationError):
        ConfluenceConnector().test_connection(
            {"base_url": "https://x.atlassian.net", "space_key": "ENG"}, "a@b.com:bad"
        )


def test_confluence_strip_html():
    from apps.api.services.connectors.confluence import _strip_html

    assert _strip_html("<p>Hello <b>world</b></p>") == "Hello  world"
    assert _strip_html("") == ""
    assert _strip_html(None) == ""
