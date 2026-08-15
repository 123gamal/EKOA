"""Notion connector: connect/validate, sync a page or database, health check.

Implements :class:`ConnectorAdapter` using a Notion internal integration
token (simple Bearer auth — see ekoa's Phase 14 planning notes on why this
was chosen over Notion's public-integration OAuth flow: this connects one
specific workspace to one specific EKOA instance, so OAuth's added
consent-screen/redirect complexity buys nothing here).
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
)

logger = logging.getLogger(__name__)

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
DEFAULT_TIMEOUT = httpx.Timeout(30.0)


def _normalise_config(config: dict) -> tuple[str | None, str | None]:
    page_id = (config.get("page_id") or "").strip() or None
    database_id = (config.get("database_id") or "").strip() or None
    if not page_id and not database_id:
        raise ConnectorValidationError("Notion config requires 'page_id' or 'database_id'")
    return page_id, database_id


def _notion_request(method: str, url: str, access_token: str, **kwargs: Any) -> httpx.Response:
    """Perform a Notion API call. Module-level so tests can monkeypatch one seam."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        return client.request(method, url, headers=headers, **kwargs)


class NotionConnector(ConnectorAdapter):
    """Adapter for a Notion page or database connected with an integration token."""

    provider = "notion"

    def test_connection(self, config: dict, access_token: str) -> dict:
        page_id, database_id = _normalise_config(config)
        resource_id = database_id or page_id
        endpoint = "databases" if database_id else "pages"

        resp = _notion_request("GET", f"{NOTION_API}/{endpoint}/{resource_id}", access_token)
        if resp.status_code == 401:
            raise ConnectorValidationError(
                "Notion rejected the integration token — it is invalid or revoked"
            )
        if resp.status_code == 404:
            raise ConnectorValidationError(
                f"{'Database' if database_id else 'Page'} '{resource_id}' was not found, "
                "or this integration hasn't been added to it (Share -> Add connections)"
            )
        if resp.status_code != 200:
            raise ConnectorValidationError(
                f"Notion API returned HTTP {resp.status_code} while validating the connection"
            )
        data = resp.json()
        title = _extract_title(data)
        return {
            "page_id": page_id,
            "database_id": database_id,
            "title": title,
        }

    def _database_page_ids(self, database_id: str, access_token: str) -> list[str]:
        page_ids: list[str] = []
        cursor: str | None = None
        while True:
            body: dict[str, Any] = {}
            if cursor:
                body["start_cursor"] = cursor
            resp = _notion_request(
                "POST", f"{NOTION_API}/databases/{database_id}/query", access_token, json=body
            )
            if resp.status_code == 401:
                raise ConnectorValidationError(
                    "Notion rejected the integration token during sync"
                )
            if resp.status_code != 200:
                raise ConnectorSyncError(
                    f"Notion could not query database '{database_id}' (HTTP {resp.status_code})"
                )
            data = resp.json()
            page_ids.extend(r["id"] for r in data.get("results", []))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return page_ids

    def _block_children_text(self, block_id: str, access_token: str, depth: int = 0) -> str:
        if depth > 5:  # guard against pathological nesting
            return ""
        texts: list[str] = []
        cursor: str | None = None
        while True:
            params = {"start_cursor": cursor} if cursor else {}
            resp = _notion_request(
                "GET", f"{NOTION_API}/blocks/{block_id}/children", access_token, params=params
            )
            if resp.status_code != 200:
                raise ConnectorSyncError(
                    f"Notion could not fetch blocks for '{block_id}' (HTTP {resp.status_code})"
                )
            data = resp.json()
            for block in data.get("results", []):
                texts.append(_block_to_text(block))
                if block.get("has_children"):
                    texts.append(
                        self._block_children_text(block["id"], access_token, depth + 1)
                    )
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return "\n".join(t for t in texts if t)

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
        """Fetch the page (or every page in the database) and index as Documents."""
        from apps.api.models.document import Document
        from apps.api.models.document_version import DocumentVersion
        from apps.api.db.base import Base
        from apps.worker.chunking import chunk_text
        from apps.worker.embeddings import ensure_collection, generate_embeddings, index_chunks
        from apps.worker.workflow_executor import get_sync_engine
        from ekoa_utils.naming import workspace_collection_name
        from sqlalchemy.orm import Session

        validated = self.test_connection(config, access_token)
        page_id, database_id = validated["page_id"], validated["database_id"]

        page_ids = (
            self._database_page_ids(database_id, access_token) if database_id else [page_id]
        )

        engine = engine or get_sync_engine()
        Base.metadata.create_all(engine, checkfirst=True)

        collection_name = workspace_collection_name(workspace_id)
        result = ConnectorSyncResult()

        with Session(engine) as db:
            for pid in page_ids:
                try:
                    meta_resp = _notion_request("GET", f"{NOTION_API}/pages/{pid}", access_token)
                    if meta_resp.status_code != 200:
                        raise ConnectorSyncError(
                            f"Notion could not fetch page '{pid}' (HTTP {meta_resp.status_code})"
                        )
                    meta = meta_resp.json()
                    title = _extract_title(meta) or pid
                    body = self._block_children_text(pid, access_token)
                except ConnectorSyncError as exc:
                    result.files_failed += 1
                    result.details.append(f"{pid}: {exc}")
                    logger.warning("Notion sync page failed %s: %s", pid, exc)
                    continue

                identity = f"notion://{pid}"
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
                        f"Embedding/index infrastructure failed for '{pid}': "
                        f"{type(exc).__name__}: {exc}"
                    ) from exc

                if doc is None:
                    doc = Document(
                        title=title[:255],
                        content_type="text/plain",
                        status="PROCESSING",
                        source_url=f"https://www.notion.so/{pid.replace('-', '')}",
                        file_path=identity,
                        workspace_id=workspace_id,
                        uploaded_by=uploaded_by,
                        metadata_json={
                            "connector": self.provider,
                            "page_id": pid,
                            "source": "notion",
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
                        f"Failed to index '{pid}' into the vector store: "
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
                result.details.append(f"{pid}: indexed {chunk_count} chunks (v{version_number})")

            db.commit()

        result.details.insert(
            0,
            f"pages={len(page_ids)} created={result.files_created} skipped={result.files_skipped} "
            f"failed={result.files_failed} chunks={result.chunk_count}",
        )
        return result

    def health_check(self, config: dict, access_token: str, connector_status: dict) -> ConnectorHealth:
        page_id, database_id = _normalise_config(config)
        resource_id = database_id or page_id
        endpoint = "databases" if database_id else "pages"
        try:
            resp = _notion_request(
                "GET", f"{NOTION_API}/{endpoint}/{resource_id}", access_token
            )
        except httpx.HTTPError as exc:
            return ConnectorHealth(
                token_valid=False,
                detail=f"Notion unreachable: {type(exc).__name__}",
                last_sync_status=connector_status.get("last_sync_status"),
                last_sync_error=connector_status.get("last_sync_error"),
                last_sync_at=connector_status.get("last_sync_at"),
            )

        if resp.status_code == 200:
            return ConnectorHealth(
                token_valid=True,
                detail="Token valid, resource accessible",
                last_sync_status=connector_status.get("last_sync_status"),
                last_sync_error=connector_status.get("last_sync_error"),
                last_sync_at=connector_status.get("last_sync_at"),
            )
        if resp.status_code == 401:
            return ConnectorHealth(
                token_valid=False,
                detail="Stored integration token is invalid or revoked",
                last_sync_status=connector_status.get("last_sync_status"),
                last_sync_error=connector_status.get("last_sync_error"),
                last_sync_at=connector_status.get("last_sync_at"),
            )
        return ConnectorHealth(
            token_valid=False,
            detail=f"Resource check failed (HTTP {resp.status_code})",
            last_sync_status=connector_status.get("last_sync_status"),
            last_sync_error=connector_status.get("last_sync_error"),
            last_sync_at=connector_status.get("last_sync_at"),
        )

    def identity_key(self, validated_config: dict) -> str | None:
        return validated_config.get("database_id") or validated_config.get("page_id")


def _extract_title(data: dict) -> str:
    """Pull a display title out of a Notion page or database object."""
    # Databases: top-level "title" (rich text array). Pages: title lives
    # inside properties, in whichever property has type "title".
    if "title" in data and isinstance(data["title"], list):
        return _rich_text_to_str(data["title"])
    for prop in (data.get("properties") or {}).values():
        if prop.get("type") == "title":
            return _rich_text_to_str(prop.get("title", []))
    return ""


def _rich_text_to_str(rich_text: list[dict]) -> str:
    return "".join(t.get("plain_text", "") for t in rich_text)


def _block_to_text(block: dict) -> str:
    """Flatten one Notion block's rich text to a plain-text line."""
    block_type = block.get("type")
    payload = block.get(block_type, {}) if block_type else {}
    rich_text = payload.get("rich_text") if isinstance(payload, dict) else None
    if rich_text:
        return _rich_text_to_str(rich_text)
    return ""
