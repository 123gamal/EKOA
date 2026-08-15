"""MS Teams connector: OAuth2 (via Microsoft Graph), sync team/channel structure.

Scope decision: indexes team + channel names/descriptions only, not channel
message content. Reading actual channel messages requires the
``ChannelMessage.Read.All`` delegated permission, which is a separate Azure
AD API-permission grant from ``Team.ReadBasic.All``/``Channel.ReadBasic.All``
(the ones actually granted for this app) — rather than block on another
Azure Portal round-trip mid-flow, this ships a real, working connector on the
permissions already granted, honestly scoped down instead of silently
failing with 403s. Extending to message content is a one-permission,
one-file follow-up once ``ChannelMessage.Read.All`` is added.
"""

from __future__ import annotations

import hashlib
import logging

from apps.api.services.connectors._microsoft_common import GRAPH_API, MicrosoftOAuthMixin, graph_request
from apps.api.services.connectors.base import (
    ConnectorAdapter,
    ConnectorHealth,
    ConnectorSyncError,
    ConnectorSyncResult,
    ConnectorValidationError,
)

logger = logging.getLogger(__name__)


class MsTeamsConnector(MicrosoftOAuthMixin, ConnectorAdapter):
    """Adapter for an MS Teams account connected via Microsoft Graph OAuth2."""

    provider = "ms_teams"
    auth_type = "oauth2"
    graph_scope = "Team.ReadBasic.All Channel.ReadBasic.All"

    def test_connection(self, config: dict, access_token: str) -> dict:
        resp = graph_request("GET", f"{GRAPH_API}/me", access_token, params={"$select": "mail,userPrincipalName"})
        if resp.status_code == 401:
            raise ConnectorValidationError("Microsoft rejected the access token — it is invalid or expired")
        if resp.status_code != 200:
            raise ConnectorValidationError(f"Microsoft Graph returned HTTP {resp.status_code} while validating the connection")
        data = resp.json()
        account = data.get("mail") or data.get("userPrincipalName") or ""
        return {"account": account}

    def _fetch_teams_and_channels(self, access_token: str) -> list[dict]:
        resp = graph_request("GET", f"{GRAPH_API}/me/joinedTeams", access_token)
        if resp.status_code == 401:
            raise ConnectorValidationError("Microsoft rejected the access token during sync")
        if resp.status_code != 200:
            raise ConnectorSyncError(f"MS Teams could not list joined teams (HTTP {resp.status_code})")
        teams = resp.json().get("value", [])

        result = []
        for team in teams:
            team_id = team["id"]
            ch_resp = graph_request("GET", f"{GRAPH_API}/teams/{team_id}/channels", access_token)
            channels = ch_resp.json().get("value", []) if ch_resp.status_code == 200 else []
            result.append({"team": team, "channels": channels})
        return result

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
        from apps.api.models.document import Document
        from apps.api.models.document_version import DocumentVersion
        from apps.api.db.base import Base
        from apps.worker.chunking import chunk_text
        from apps.worker.embeddings import ensure_collection, generate_embeddings, index_chunks
        from apps.worker.workflow_executor import get_sync_engine
        from ekoa_utils.naming import workspace_collection_name
        from sqlalchemy.orm import Session

        teams_data = self._fetch_teams_and_channels(access_token)
        engine = engine or get_sync_engine()
        Base.metadata.create_all(engine, checkfirst=True)
        collection_name = workspace_collection_name(workspace_id)
        result = ConnectorSyncResult()

        with Session(engine) as db:
            for entry in teams_data:
                team = entry["team"]
                team_id = team["id"]
                team_name = team.get("displayName", team_id)
                lines = [f"Team: {team_name}", f"Description: {team.get('description', '')}", "", "Channels:"]
                for ch in entry["channels"]:
                    lines.append(f"- {ch.get('displayName', '')}: {ch.get('description', '')}")
                body = "\n".join(lines)

                identity = f"msteams://{team_id}"
                checksum = hashlib.sha256(body.encode("utf-8")).hexdigest()

                doc = (
                    db.query(Document)
                    .filter(Document.workspace_id == workspace_id, Document.file_path == identity, Document.deleted_at.is_(None))
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
                    raise ConnectorSyncError(f"Embedding/index infrastructure failed for team '{team_name}': {type(exc).__name__}: {exc}") from exc

                if doc is None:
                    doc = Document(
                        title=f"MS Teams: {team_name}"[:255],
                        content_type="text/plain",
                        status="PROCESSING",
                        source_url=team.get("webUrl"),
                        file_path=identity,
                        workspace_id=workspace_id,
                        uploaded_by=uploaded_by,
                        metadata_json={"connector": self.provider, "team_id": team_id, "source": "ms_teams"},
                    )
                    db.add(doc)
                    db.flush()
                    version_number = 1
                    result.files_created += 1
                else:
                    version_number = (
                        db.query(DocumentVersion).filter(DocumentVersion.document_id == doc.id).count()
                    ) + 1

                try:
                    chunk_count = (
                        index_chunks(collection_name, doc.id, chunks, embeddings, organization_id=organization_id, workspace_id=workspace_id)
                        if chunks else 0
                    )
                except Exception as exc:  # noqa: BLE001
                    db.rollback()
                    raise ConnectorSyncError(f"Failed to index team '{team_name}' into the vector store: {type(exc).__name__}: {exc}") from exc

                db.add(DocumentVersion(document_id=doc.id, version=version_number, file_path=identity, checksum=checksum, status="INDEXED", uploaded_by=uploaded_by))
                doc.status = "INDEXED"
                doc.chunk_count = chunk_count
                result.files_processed += 1
                result.chunk_count += chunk_count
                result.details.append(f"{team_name}: {len(entry['channels'])} channel(s), {chunk_count} chunks (v{version_number})")

            db.commit()

        result.details.insert(0, f"teams={len(teams_data)} created={result.files_created} skipped={result.files_skipped} failed={result.files_failed}")
        return result

    def health_check(self, config: dict, access_token: str, connector_status: dict) -> ConnectorHealth:
        try:
            resp = graph_request("GET", f"{GRAPH_API}/me", access_token, params={"$select": "mail"})
        except Exception as exc:  # noqa: BLE001
            return ConnectorHealth(
                token_valid=False,
                detail=f"MS Teams unreachable: {type(exc).__name__}",
                last_sync_status=connector_status.get("last_sync_status"),
                last_sync_error=connector_status.get("last_sync_error"),
                last_sync_at=connector_status.get("last_sync_at"),
            )
        if resp.status_code == 200:
            return ConnectorHealth(
                token_valid=True,
                detail="Token valid",
                last_sync_status=connector_status.get("last_sync_status"),
                last_sync_error=connector_status.get("last_sync_error"),
                last_sync_at=connector_status.get("last_sync_at"),
            )
        return ConnectorHealth(
            token_valid=False,
            detail=f"Check failed (HTTP {resp.status_code})",
            last_sync_status=connector_status.get("last_sync_status"),
            last_sync_error=connector_status.get("last_sync_error"),
            last_sync_at=connector_status.get("last_sync_at"),
        )

    def identity_key(self, validated_config: dict) -> str | None:
        return validated_config.get("account")
