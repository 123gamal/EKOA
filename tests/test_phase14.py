"""Phase 14 tests: Jira/Notion/Slack/Google Drive connector adapters.

Mocks the single HTTP-request seam each adapter module exposes (mirroring
the pattern used for GitHub's ``_github_request``), same style as
``tests/test_phase8.py``'s MCP key tests. Live end-to-end sync against the
real providers is covered separately (this session's live verification, not
part of the automated suite, since it needs real third-party credentials).
"""

from __future__ import annotations

import httpx
import pytest

from apps.api.services.connectors.base import ConnectorValidationError, get_connector_adapter
from apps.api.services.connectors.jira import JiraConnector
from apps.api.services.connectors.notion import NotionConnector
from apps.api.services.connectors.slack import SlackConnector
from apps.api.services.connectors.google_drive import GoogleDriveConnector, token_expired


def _resp(status_code: int, json_body: dict) -> httpx.Response:
    return httpx.Response(status_code, json=json_body, request=httpx.Request("GET", "http://x"))


# ── Registry ─────────────────────────────────────────────────────────────────


def test_registry_resolves_all_phase14_providers():
    assert isinstance(get_connector_adapter("jira"), JiraConnector)
    assert isinstance(get_connector_adapter("notion"), NotionConnector)
    assert isinstance(get_connector_adapter("slack"), SlackConnector)
    assert isinstance(get_connector_adapter("google_drive"), GoogleDriveConnector)
    with pytest.raises(ConnectorValidationError):
        get_connector_adapter("not_a_real_provider")


# ── Jira ─────────────────────────────────────────────────────────────────────


def test_jira_split_credential_requires_colon():
    with pytest.raises(ConnectorValidationError):
        JiraConnector._split_credential("no-colon-here")
    email, token = JiraConnector._split_credential("a@b.com:sometoken")
    assert email == "a@b.com" and token == "sometoken"


def test_jira_test_connection_success(monkeypatch):
    calls = []

    def fake_request(method, url, email, api_token, **kwargs):
        calls.append(url)
        if url.endswith("/myself"):
            return _resp(200, {"displayName": "Test User"})
        return _resp(200, {"name": "Engineering"})

    monkeypatch.setattr("apps.api.services.connectors.jira._jira_request", fake_request)
    adapter = JiraConnector()
    result = adapter.test_connection(
        {"base_url": "https://x.atlassian.net", "project_key": "eng"}, "a@b.com:tok"
    )
    assert result["project_key"] == "ENG"
    assert result["project_name"] == "Engineering"
    assert adapter.identity_key(result) == "eng"


def test_jira_fetch_issues_uses_search_jql_endpoint_with_token_pagination(monkeypatch):
    """Regression test: Atlassian removed the classic GET /rest/api/3/search
    (returns 410 Gone on real Jira Cloud sites, confirmed via live
    verification) in favor of /rest/api/3/search/jql, which paginates via
    nextPageToken rather than startAt/total."""
    calls = []
    pages = [
        {"issues": [{"key": "ENG-1"}, {"key": "ENG-2"}], "nextPageToken": "tok-2"},
        {"issues": [{"key": "ENG-3"}], "nextPageToken": None},
    ]

    def fake_request(method, url, email, api_token, params=None, **kwargs):
        calls.append((url, params))
        assert url.endswith("/rest/api/3/search/jql")
        return _resp(200, pages[len(calls) - 1])

    monkeypatch.setattr("apps.api.services.connectors.jira._jira_request", fake_request)
    issues = JiraConnector()._fetch_issues("https://x.atlassian.net", "ENG", "a@b.com", "tok")

    assert [i["key"] for i in issues] == ["ENG-1", "ENG-2", "ENG-3"]
    assert len(calls) == 2
    assert "nextPageToken" not in calls[0][1]
    assert calls[1][1]["nextPageToken"] == "tok-2"


def test_jira_test_connection_rejects_bad_token(monkeypatch):
    monkeypatch.setattr(
        "apps.api.services.connectors.jira._jira_request",
        lambda *a, **k: _resp(401, {}),
    )
    with pytest.raises(ConnectorValidationError):
        JiraConnector().test_connection(
            {"base_url": "https://x.atlassian.net", "project_key": "ENG"}, "a@b.com:bad"
        )


# ── Notion ───────────────────────────────────────────────────────────────────


def test_notion_test_connection_success(monkeypatch):
    monkeypatch.setattr(
        "apps.api.services.connectors.notion._notion_request",
        lambda *a, **k: _resp(200, {"properties": {"Name": {"type": "title", "title": [{"plain_text": "My Page"}]}}}),
    )
    result = NotionConnector().test_connection({"page_id": "abc123"}, "secret_x")
    assert result["title"] == "My Page"
    assert result["page_id"] == "abc123"


def test_notion_test_connection_requires_page_or_db():
    with pytest.raises(ConnectorValidationError):
        NotionConnector().test_connection({}, "secret_x")


def test_notion_test_connection_not_shared(monkeypatch):
    monkeypatch.setattr(
        "apps.api.services.connectors.notion._notion_request",
        lambda *a, **k: _resp(404, {}),
    )
    with pytest.raises(ConnectorValidationError):
        NotionConnector().test_connection({"page_id": "abc123"}, "secret_x")


# ── Slack ────────────────────────────────────────────────────────────────────


def test_slack_test_connection_success(monkeypatch):
    monkeypatch.setattr(
        "apps.api.services.connectors.slack._slack_request",
        lambda *a, **k: _resp(200, {"ok": True, "team_id": "T123", "team": "Acme"}),
    )
    result = SlackConnector().test_connection({}, "xoxb-fake")
    assert result["team_id"] == "T123"
    assert SlackConnector().identity_key(result) == "T123"


def test_slack_test_connection_rejects_bad_token(monkeypatch):
    monkeypatch.setattr(
        "apps.api.services.connectors.slack._slack_request",
        lambda *a, **k: _resp(200, {"ok": False, "error": "invalid_auth"}),
    )
    with pytest.raises(ConnectorValidationError):
        SlackConnector().test_connection({}, "xoxb-bad")


def test_slack_oauth_authorize_url_includes_client_id(monkeypatch):
    from ekoa_config import settings as settings_mod

    monkeypatch.setattr(settings_mod.get_settings(), "SLACK_CLIENT_ID", "test-client-id")
    url = SlackConnector().oauth_authorize_url("some-state", workspace_id="ws-1")
    assert "test-client-id" in url
    assert "state=some-state" in url


# ── Google Drive ─────────────────────────────────────────────────────────────


def test_google_drive_test_connection_success(monkeypatch):
    monkeypatch.setattr(
        "apps.api.services.connectors.google_drive._drive_request",
        lambda *a, **k: _resp(200, {"user": {"emailAddress": "me@example.com"}}),
    )
    result = GoogleDriveConnector().test_connection({}, "ya29.fake")
    assert result["account"] == "me@example.com"


def test_google_drive_test_connection_rejects_expired_token(monkeypatch):
    monkeypatch.setattr(
        "apps.api.services.connectors.google_drive._drive_request",
        lambda *a, **k: _resp(401, {}),
    )
    with pytest.raises(ConnectorValidationError):
        GoogleDriveConnector().test_connection({}, "ya29.expired")


def test_token_expired_helper():
    from datetime import datetime, timedelta, timezone

    assert token_expired(None) is True
    assert token_expired(datetime.now(timezone.utc) - timedelta(minutes=1)) is True
    assert token_expired(datetime.now(timezone.utc) + timedelta(hours=1)) is False
