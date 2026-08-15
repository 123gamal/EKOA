"""Abstract connector interface.

A connector adapts an external integration (GitHub, future providers) to the
EKOA ingestion pipeline. Implementations must provide the three operations the
whole platform relies on:

- ``test_connection`` — validate credentials/config BEFORE persisting anything
  (used by the connect endpoint).
- ``sync`` — pull real content and feed it through parse → chunk → embed →
  Qdrant as Documents (used by the worker task).
- ``health_check`` — report the REAL state of the integration: whether the
  stored credential is still valid and what the last sync produced.

Errors are raised as :class:`ConnectorError` subclasses so routes can map them
to HTTP responses and workers can decide retry vs. permanent failure without
knowing provider specifics.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal


class ConnectorError(Exception):
    """Base error for any connector failure."""


class ConnectorValidationError(ConnectorError):
    """The supplied credentials/config are invalid or rejected by the provider."""


class ConnectorSyncError(ConnectorError):
    """The sync run failed permanently (non-retryable)."""


@dataclass
class ConnectorHealth:
    """Result of a health check: credential validity + last sync state."""

    token_valid: bool
    detail: str
    last_sync_status: str | None = None
    last_sync_error: str | None = None
    last_sync_at: str | None = None


@dataclass
class ConnectorSyncResult:
    """Outcome of a sync run, used to update connector bookkeeping + logging."""

    files_processed: int = 0
    files_created: int = 0
    files_skipped: int = 0
    files_failed: int = 0
    chunk_count: int = 0
    details: list[str] = field(default_factory=list)


@dataclass
class OAuthTokenResult:
    """Result of exchanging an OAuth2 authorization code for tokens.

    ``refresh_token``/``expires_in`` are ``None`` for providers whose access
    token doesn't expire (e.g. Slack bot tokens) — only providers that set
    ``expires_in`` need :meth:`ConnectorAdapter.refresh_access_token` called
    before use.
    """

    access_token: str
    refresh_token: str | None = None
    expires_in: int | None = None  # seconds
    # Provider-specific identity to store in Connector.config_json (e.g.
    # Slack's team id/name) — merged into whatever test_connection would
    # have returned for a PAT-based provider.
    config: dict = field(default_factory=dict)


class ConnectorAdapter(ABC):
    """Interface every integration provider must implement."""

    provider: str = ""
    auth_type: Literal["pat", "oauth2"] = "pat"

    @abstractmethod
    def test_connection(self, config: dict, access_token: str) -> dict:
        """Validate ``access_token`` + ``config`` against the provider.

        Returns a dict of validated/normalised config on success. Raises
        :class:`ConnectorValidationError` (or a subclass) when the credential
        is invalid/expired/revoked or the config is wrong.
        """

    @abstractmethod
    def sync(self, config: dict, access_token: str, *, workspace_id, organization_id, uploaded_by) -> ConnectorSyncResult:
        """Fetch remote content and index it as Documents (deduped by checksum)."""

    @abstractmethod
    def health_check(self, config: dict, access_token: str, connector_status: dict) -> ConnectorHealth:
        """Report real integration health: token validity + last sync state."""

    def identity_key(self, validated_config: dict) -> str | None:
        """Optional stable identity used to dedupe re-connects to the same
        remote resource (e.g. GitHub's "owner/repo"). ``None`` (the default)
        means re-connects are only matched by connector name."""
        return None

    def oauth_authorize_url(self, state: str, *, workspace_id: str) -> str:
        """Build the provider's consent-screen URL. OAuth2 adapters only."""
        raise NotImplementedError(f"{self.provider} does not support OAuth2")

    def oauth_exchange_code(self, code: str) -> OAuthTokenResult:
        """Exchange an authorization code for tokens. OAuth2 adapters only."""
        raise NotImplementedError(f"{self.provider} does not support OAuth2")

    def refresh_access_token(self, refresh_token: str) -> OAuthTokenResult:
        """Exchange a refresh token for a new access token. Only providers
        whose access tokens expire (e.g. Google) need to override this."""
        raise NotImplementedError(f"{self.provider} does not support token refresh")


def get_connector_adapter(provider: str) -> ConnectorAdapter:
    """Resolve a connector adapter by provider name (registry)."""
    if provider == "github":
        from apps.api.services.connectors.github import GitHubConnector
        return GitHubConnector()
    if provider == "jira":
        from apps.api.services.connectors.jira import JiraConnector
        return JiraConnector()
    if provider == "notion":
        from apps.api.services.connectors.notion import NotionConnector
        return NotionConnector()
    if provider == "slack":
        from apps.api.services.connectors.slack import SlackConnector
        return SlackConnector()
    if provider == "google_drive":
        from apps.api.services.connectors.google_drive import GoogleDriveConnector
        return GoogleDriveConnector()
    if provider == "google_calendar":
        from apps.api.services.connectors.google_calendar import GoogleCalendarConnector
        return GoogleCalendarConnector()
    if provider == "google_sheets":
        from apps.api.services.connectors.google_sheets import GoogleSheetsConnector
        return GoogleSheetsConnector()
    if provider == "confluence":
        from apps.api.services.connectors.confluence import ConfluenceConnector
        return ConfluenceConnector()
    raise ConnectorValidationError(f"Unsupported connector provider: {provider!r}")
