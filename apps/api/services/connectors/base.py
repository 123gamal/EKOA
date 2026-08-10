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


class ConnectorAdapter(ABC):
    """Interface every integration provider must implement."""

    provider: str = ""

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


def get_connector_adapter(provider: str) -> ConnectorAdapter:
    """Resolve a connector adapter by provider name (registry)."""
    if provider == "github":
        from apps.api.services.connectors.github import GitHubConnector
        return GitHubConnector()
    raise ConnectorValidationError(f"Unsupported connector provider: {provider!r}")
