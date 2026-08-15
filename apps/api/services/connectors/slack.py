"""Slack connector: OAuth2 install, sync channel transcripts, health check.

Implements :class:`ConnectorAdapter` with ``auth_type = "oauth2"``. Slack bot
tokens (``xoxb-...``) do not expire, so no refresh-token handling is needed —
unlike Google Drive's adapter. The OAuth authorize/callback routes live in
``apps/api/routes/oauth.py``; this module only builds the consent URL and
exchanges the code.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import httpx

from apps.api.services.connectors.base import (
    ConnectorAdapter,
    ConnectorHealth,
    ConnectorSyncError,
    ConnectorSyncResult,
    ConnectorValidationError,
    OAuthTokenResult,
)
from ekoa_config.settings import get_settings

logger = logging.getLogger(__name__)

SLACK_API = "https://slack.com/api"
DEFAULT_TIMEOUT = httpx.Timeout(30.0)
BOT_SCOPES = "channels:read,channels:history,team:read"


def _slack_request(method: str, url: str, access_token: str, **kwargs: Any) -> httpx.Response:
    headers = {"Authorization": f"Bearer {access_token}"}
    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        return client.request(method, url, headers=headers, **kwargs)


class SlackConnector(ConnectorAdapter):
    """Adapter for a Slack workspace connected via OAuth2 (bot token)."""

    provider = "slack"
    auth_type = "oauth2"

    def oauth_authorize_url(self, state: str, *, workspace_id: str) -> str:
        settings = get_settings()
        return (
            "https://slack.com/oauth/v2/authorize"
            f"?client_id={settings.SLACK_CLIENT_ID}"
            f"&scope={BOT_SCOPES}"
            f"&redirect_uri={settings.SLACK_OAUTH_REDIRECT_URI}"
            f"&state={state}"
        )

    def oauth_exchange_code(self, code: str) -> OAuthTokenResult:
        settings = get_settings()
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            resp = client.post(
                f"{SLACK_API}/oauth.v2.access",
                data={
                    "client_id": settings.SLACK_CLIENT_ID,
                    "client_secret": settings.SLACK_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": settings.SLACK_OAUTH_REDIRECT_URI,
                },
            )
        data = resp.json()
        if not data.get("ok"):
            raise ConnectorValidationError(
                f"Slack OAuth exchange failed: {data.get('error', 'unknown_error')}"
            )
        team = data.get("team", {}) or {}
        return OAuthTokenResult(
            access_token=data["access_token"],
            config={"team_id": team.get("id", ""), "team_name": team.get("name", "")},
        )

    def test_connection(self, config: dict, access_token: str) -> dict:
        """PAT-style path is unused for Slack (OAuth-only), but implemented
        for interface completeness / potential future bot-token-paste flow."""
        resp = _slack_request("POST", f"{SLACK_API}/auth.test", access_token)
        data = resp.json()
        if not data.get("ok"):
            raise ConnectorValidationError(
                f"Slack rejected the token: {data.get('error', 'unknown_error')}"
            )
        return {
            "team_id": data.get("team_id", config.get("team_id", "")),
            "team_name": data.get("team", config.get("team_name", "")),
        }

    def _list_channels(self, access_token: str) -> list[dict]:
        channels: list[dict] = []
        cursor = ""
        while True:
            params = {"types": "public_channel", "limit": 200}
            if cursor:
                params["cursor"] = cursor
            resp = _slack_request(
                "GET", f"{SLACK_API}/conversations.list", access_token, params=params
            )
            data = resp.json()
            if not data.get("ok"):
                raise ConnectorSyncError(
                    f"Slack could not list channels: {data.get('error', 'unknown_error')}"
                )
            channels.extend(c for c in data.get("channels", []) if c.get("is_member"))
            cursor = (data.get("response_metadata") or {}).get("next_cursor") or ""
            if not cursor:
                break
        return channels

    def _channel_transcript(self, channel_id: str, access_token: str) -> str:
        lines: list[str] = []
        cursor = ""
        while True:
            params: dict[str, Any] = {"channel": channel_id, "limit": 200}
            if cursor:
                params["cursor"] = cursor
            resp = _slack_request(
                "GET", f"{SLACK_API}/conversations.history", access_token, params=params
            )
            data = resp.json()
            if not data.get("ok"):
                raise ConnectorSyncError(
                    f"Slack could not fetch history for '{channel_id}': "
                    f"{data.get('error', 'unknown_error')}"
                )
            for msg in data.get("messages", []):
                text = msg.get("text", "")
                user = msg.get("user", "unknown")
                if text:
                    lines.append(f"{user}: {text}")
            cursor = (data.get("response_metadata") or {}).get("next_cursor") or ""
            if not cursor:
                break
        # Oldest-first reads more naturally as a transcript.
        return "\n".join(reversed(lines))

    def sync(
        self,
        config: dict,
        access_token: str,
        *,
        workspace_id,
        organization_id,
        uploaded_by,
        engine=None,
    ) -> ConnectorSyncResult:
        """Sync every public channel the bot has been invited to as one
        transcript Document each (whole-transcript re-sync, deduped by
        checksum — same pattern as GitHub/Jira/Notion)."""
        from apps.api.models.document import Document
        from apps.api.models.document_version import DocumentVersion
        from apps.api.db.base import Base
        from apps.worker.chunking import chunk_text
        from apps.worker.embeddings import ensure_collection, generate_embeddings, index_chunks
        from apps.worker.workflow_executor import get_sync_engine
        from ekoa_utils.naming import workspace_collection_name
        from sqlalchemy.orm import Session

        team_id = config.get("team_id", "")
        channels = self._list_channels(access_token)

        engine = engine or get_sync_engine()
        Base.metadata.create_all(engine, checkfirst=True)

        collection_name = workspace_collection_name(workspace_id)
        result = ConnectorSyncResult()

        with Session(engine) as db:
            for channel in channels:
                channel_id = channel["id"]
                channel_name = channel.get("name", channel_id)
                try:
                    body = self._channel_transcript(channel_id, access_token)
                except ConnectorSyncError as exc:
                    result.files_failed += 1
                    result.details.append(f"#{channel_name}: {exc}")
                    logger.warning("Slack sync channel failed %s: %s", channel_id, exc)
                    continue

                identity = f"slack://{team_id}/{channel_id}"
                checksum = hashlib.sha256(body.encode("utf-8")).hexdigest()

                doc = (
                    db.query(Document)
                    .filter(
                        Document.workspace_id == workspace_id,
                        Document.file_path == identity,
                        Document.deleted_at.is_(None),
                    )
                    .first()
                )
                latest_checksum = None
                if doc is not None:
                    latest = (
                        db.query(DocumentVersion)
                        .filter(DocumentVersion.document_id == doc.id)
                        .order_by(DocumentVersion.version.desc())
                        .first()
                    )
                    latest_checksum = latest.checksum if latest else None

                if doc is not None and latest_checksum == checksum:
                    result.files_skipped += 1
                    continue

                chunks = chunk_text(body) if body else []
                try:
                    embeddings = generate_embeddings(chunks) if chunks else []
                    vector_size = len(embeddings[0]) if embeddings else 384
                    ensure_collection(collection_name, vector_size=vector_size)
                except Exception as exc:  # noqa: BLE001
                    db.rollback()
                    raise ConnectorSyncError(
                        f"Embedding/index infrastructure failed for '#{channel_name}': "
                        f"{type(exc).__name__}: {exc}"
                    ) from exc

                if doc is None:
                    doc = Document(
                        title=f"#{channel_name} transcript",
                        content_type="text/plain",
                        status="PROCESSING",
                        source_url=f"https://app.slack.com/client/{team_id}/{channel_id}",
                        file_path=identity,
                        workspace_id=workspace_id,
                        uploaded_by=uploaded_by,
                        metadata_json={
                            "connector": self.provider,
                            "team_id": team_id,
                            "channel_id": channel_id,
                            "channel_name": channel_name,
                            "source": "slack",
                        },
                    )
                    db.add(doc)
                    db.flush()
                    version_number = 1
                    result.files_created += 1
                else:
                    version_number = (
                        db.query(DocumentVersion)
                        .filter(DocumentVersion.document_id == doc.id)
                        .count()
                    ) + 1

                try:
                    chunk_count = (
                        index_chunks(
                            collection_name,
                            doc.id,
                            chunks,
                            embeddings,
                            organization_id=organization_id,
                            workspace_id=workspace_id,
                        )
                        if chunks
                        else 0
                    )
                except Exception as exc:  # noqa: BLE001
                    db.rollback()
                    raise ConnectorSyncError(
                        f"Failed to index '#{channel_name}' into the vector store: "
                        f"{type(exc).__name__}: {exc}"
                    ) from exc

                db.add(
                    DocumentVersion(
                        document_id=doc.id,
                        version=version_number,
                        file_path=identity,
                        checksum=checksum,
                        status="INDEXED",
                        uploaded_by=uploaded_by,
                    )
                )
                doc.status = "INDEXED"
                doc.chunk_count = chunk_count
                result.files_processed += 1
                result.chunk_count += chunk_count
                result.details.append(
                    f"#{channel_name}: indexed {chunk_count} chunks (v{version_number})"
                )

            db.commit()

        result.details.insert(
            0,
            f"team={team_id} channels={len(channels)} created={result.files_created} "
            f"skipped={result.files_skipped} failed={result.files_failed} chunks={result.chunk_count}",
        )
        return result

    def health_check(self, config: dict, access_token: str, connector_status: dict) -> ConnectorHealth:
        try:
            resp = _slack_request("POST", f"{SLACK_API}/auth.test", access_token)
            data = resp.json()
        except httpx.HTTPError as exc:
            return ConnectorHealth(
                token_valid=False,
                detail=f"Slack unreachable: {type(exc).__name__}",
                last_sync_status=connector_status.get("last_sync_status"),
                last_sync_error=connector_status.get("last_sync_error"),
                last_sync_at=connector_status.get("last_sync_at"),
            )

        if data.get("ok"):
            return ConnectorHealth(
                token_valid=True,
                detail=f"Token valid for team '{data.get('team', 'unknown')}'",
                last_sync_status=connector_status.get("last_sync_status"),
                last_sync_error=connector_status.get("last_sync_error"),
                last_sync_at=connector_status.get("last_sync_at"),
            )
        return ConnectorHealth(
            token_valid=False,
            detail=f"Stored token is invalid or revoked: {data.get('error', 'unknown_error')}",
            last_sync_status=connector_status.get("last_sync_status"),
            last_sync_error=connector_status.get("last_sync_error"),
            last_sync_at=connector_status.get("last_sync_at"),
        )

    def identity_key(self, validated_config: dict) -> str | None:
        return validated_config.get("team_id")
