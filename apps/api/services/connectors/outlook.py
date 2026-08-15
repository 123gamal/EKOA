"""Outlook connector: OAuth2 (via Microsoft Graph), sync recent mail.

One rolled-up "mail digest" Document per sync (same reasoning as Google
Calendar: many tiny per-message documents are lower value than one
digest — deliberate, not a corner cut).
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

MESSAGE_FIELDS = "subject,from,receivedDateTime,bodyPreview"


class OutlookConnector(MicrosoftOAuthMixin, ConnectorAdapter):
    """Adapter for an Outlook mailbox connected via Microsoft Graph OAuth2."""

    provider = "outlook"
    auth_type = "oauth2"
    graph_scope = "Mail.Read"

    def test_connection(self, config: dict, access_token: str) -> dict:
        resp = graph_request("GET", f"{GRAPH_API}/me", access_token, params={"$select": "mail,userPrincipalName"})
        if resp.status_code == 401:
            raise ConnectorValidationError("Microsoft rejected the access token — it is invalid or expired")
        if resp.status_code != 200:
            raise ConnectorValidationError(f"Microsoft Graph returned HTTP {resp.status_code} while validating the connection")
        data = resp.json()
        account = data.get("mail") or data.get("userPrincipalName") or ""
        return {"account": account}

    def _fetch_messages(self, access_token: str, limit: int = 50) -> list[dict]:
        resp = graph_request(
            "GET",
            f"{GRAPH_API}/me/messages",
            access_token,
            params={"$top": limit, "$select": MESSAGE_FIELDS, "$orderby": "receivedDateTime desc"},
        )
        if resp.status_code == 401:
            raise ConnectorValidationError("Microsoft rejected the access token during sync")
        if resp.status_code != 200:
            raise ConnectorSyncError(f"Outlook could not list messages (HTTP {resp.status_code})")
        return resp.json().get("value", [])

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

        validated = self.test_connection(config, access_token)
        account = validated["account"]
        messages = self._fetch_messages(access_token)

        lines = []
        for m in messages:
            sender = ((m.get("from") or {}).get("emailAddress") or {}).get("address", "unknown")
            lines.append(
                f"[{m.get('receivedDateTime', '')}] From: {sender} — Subject: {m.get('subject', '')}\n"
                f"{m.get('bodyPreview', '')}"
            )
        body = "\n\n".join(lines)

        engine = engine or get_sync_engine()
        Base.metadata.create_all(engine, checkfirst=True)
        collection_name = workspace_collection_name(workspace_id)
        result = ConnectorSyncResult()

        identity = f"outlook://{account}/digest"
        checksum = hashlib.sha256(body.encode("utf-8")).hexdigest()

        with Session(engine) as db:
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
                result.details.append(f"mail digest unchanged ({len(messages)} messages)")
                return result

            chunks = chunk_text(body) if body else []
            embeddings = generate_embeddings(chunks) if chunks else []
            vector_size = len(embeddings[0]) if embeddings else 384
            ensure_collection(collection_name, vector_size=vector_size)

            if doc is None:
                doc = Document(
                    title=f"Outlook mail digest ({account})"[:255],
                    content_type="text/plain",
                    status="PROCESSING",
                    source_url="https://outlook.office.com/mail/",
                    file_path=identity,
                    workspace_id=workspace_id,
                    uploaded_by=uploaded_by,
                    metadata_json={"connector": self.provider, "account": account, "source": "outlook"},
                )
                db.add(doc)
                db.flush()
                version_number = 1
                result.files_created += 1
            else:
                version_number = (
                    db.query(DocumentVersion).filter(DocumentVersion.document_id == doc.id).count()
                ) + 1

            chunk_count = (
                index_chunks(collection_name, doc.id, chunks, embeddings, organization_id=organization_id, workspace_id=workspace_id)
                if chunks else 0
            )
            db.add(DocumentVersion(document_id=doc.id, version=version_number, file_path=identity, checksum=checksum, status="INDEXED", uploaded_by=uploaded_by))
            doc.status = "INDEXED"
            doc.chunk_count = chunk_count
            result.files_processed += 1
            result.chunk_count += chunk_count
            result.details.append(f"mail digest: {len(messages)} messages, {chunk_count} chunks (v{version_number})")

            db.commit()

        return result

    def health_check(self, config: dict, access_token: str, connector_status: dict) -> ConnectorHealth:
        try:
            resp = graph_request("GET", f"{GRAPH_API}/me", access_token, params={"$select": "mail"})
        except Exception as exc:  # noqa: BLE001
            return ConnectorHealth(
                token_valid=False,
                detail=f"Outlook unreachable: {type(exc).__name__}",
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
