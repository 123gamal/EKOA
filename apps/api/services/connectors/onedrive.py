"""OneDrive connector: OAuth2 (via Microsoft Graph), sync files.

Text-extractable files (.txt/.md) are exported as content Documents;
everything else is indexed metadata-only (name/size/path in the body) — the
same "don't silently drop, index what we honestly can" approach used
elsewhere rather than skipping non-text files outright.
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

TEXT_EXTENSIONS = (".txt", ".md", ".csv")


class OneDriveConnector(MicrosoftOAuthMixin, ConnectorAdapter):
    """Adapter for a OneDrive account connected via Microsoft Graph OAuth2."""

    provider = "onedrive"
    auth_type = "oauth2"
    graph_scope = "Files.Read.All"

    def test_connection(self, config: dict, access_token: str) -> dict:
        resp = graph_request("GET", f"{GRAPH_API}/me", access_token, params={"$select": "mail,userPrincipalName"})
        if resp.status_code == 401:
            raise ConnectorValidationError("Microsoft rejected the access token — it is invalid or expired")
        if resp.status_code != 200:
            raise ConnectorValidationError(f"Microsoft Graph returned HTTP {resp.status_code} while validating the connection")
        data = resp.json()
        account = data.get("mail") or data.get("userPrincipalName") or ""
        return {"account": account}

    def _list_files(self, access_token: str) -> list[dict]:
        resp = graph_request("GET", f"{GRAPH_API}/me/drive/root/children", access_token, params={"$top": 100})
        if resp.status_code == 401:
            raise ConnectorValidationError("Microsoft rejected the access token during sync")
        if resp.status_code != 200:
            raise ConnectorSyncError(f"OneDrive could not list files (HTTP {resp.status_code})")
        return [f for f in resp.json().get("value", []) if "file" in f]

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

        files = self._list_files(access_token)
        engine = engine or get_sync_engine()
        Base.metadata.create_all(engine, checkfirst=True)
        collection_name = workspace_collection_name(workspace_id)
        result = ConnectorSyncResult()

        with Session(engine) as db:
            for f in files:
                file_id, name = f["id"], f.get("name", f["id"])
                is_text = name.lower().endswith(TEXT_EXTENSIONS)
                if is_text:
                    dl = graph_request("GET", f"{GRAPH_API}/me/drive/items/{file_id}/content", access_token)
                    body = dl.text if dl.status_code == 200 else f"[Could not download content: HTTP {dl.status_code}]"
                else:
                    size = f.get("size", 0)
                    body = f"File: {name}\nSize: {size} bytes\n(Binary/non-text file — metadata only, content not extracted.)"

                identity = f"onedrive://{file_id}"
                modified = f.get("lastModifiedDateTime", "")
                checksum = hashlib.sha256(f"{modified}:{body}".encode("utf-8")).hexdigest()

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
                    raise ConnectorSyncError(f"Embedding/index infrastructure failed for '{name}': {type(exc).__name__}: {exc}") from exc

                if doc is None:
                    doc = Document(
                        title=name[:255],
                        content_type="text/plain" if is_text else "application/octet-stream",
                        status="PROCESSING",
                        source_url=f.get("webUrl"),
                        file_path=identity,
                        workspace_id=workspace_id,
                        uploaded_by=uploaded_by,
                        metadata_json={"connector": self.provider, "file_id": file_id, "source": "onedrive"},
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
                    raise ConnectorSyncError(f"Failed to index '{name}' into the vector store: {type(exc).__name__}: {exc}") from exc

                db.add(DocumentVersion(document_id=doc.id, version=version_number, file_path=identity, checksum=checksum, status="INDEXED", uploaded_by=uploaded_by))
                doc.status = "INDEXED"
                doc.chunk_count = chunk_count
                result.files_processed += 1
                result.chunk_count += chunk_count
                result.details.append(f"{name}: {chunk_count} chunks (v{version_number})")

            db.commit()

        result.details.insert(0, f"files={len(files)} created={result.files_created} skipped={result.files_skipped} failed={result.files_failed}")
        return result

    def health_check(self, config: dict, access_token: str, connector_status: dict) -> ConnectorHealth:
        try:
            resp = graph_request("GET", f"{GRAPH_API}/me", access_token, params={"$select": "mail"})
        except Exception as exc:  # noqa: BLE001
            return ConnectorHealth(
                token_valid=False,
                detail=f"OneDrive unreachable: {type(exc).__name__}",
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
