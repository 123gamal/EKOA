"""Confluence connector: connect/validate, sync a space's pages, health check.

Implements :class:`ConnectorAdapter` using the same ``email:api_token`` HTTP
Basic auth as the Jira connector — Confluence and Jira Cloud share one
Atlassian account/API token, so a user who already connected Jira can reuse
the exact same credential here.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import re
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

DEFAULT_TIMEOUT = httpx.Timeout(30.0)
PAGE_SIZE = 50
_TAG_RE = re.compile(r"<[^>]+>")


def _normalise_config(config: dict) -> tuple[str, str]:
    base_url = (config.get("base_url") or "").strip().rstrip("/")
    space_key = (config.get("space_key") or "").strip().upper()
    if not base_url or not space_key:
        raise ConnectorValidationError("Confluence config requires 'base_url' and 'space_key'")
    return base_url, space_key


def _basic_auth_header(email: str, api_token: str) -> str:
    raw = f"{email}:{api_token}".encode("utf-8")
    return f"Basic {base64.b64encode(raw).decode('ascii')}"


def _confluence_request(method: str, url: str, email: str, api_token: str, **kwargs: Any) -> httpx.Response:
    headers = {
        "Accept": "application/json",
        "Authorization": _basic_auth_header(email, api_token),
    }
    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        return client.request(method, url, headers=headers, **kwargs)


def _strip_html(html: str) -> str:
    return _TAG_RE.sub(" ", html or "").replace("&nbsp;", " ").strip()


class ConfluenceConnector(ConnectorAdapter):
    """Adapter for a Confluence space connected with an email + API token."""

    provider = "confluence"

    @staticmethod
    def _split_credential(access_token: str) -> tuple[str, str]:
        if ":" not in access_token:
            raise ConnectorValidationError(
                "Confluence credential must be 'email:api_token' (colon-separated)"
            )
        email, _, api_token = access_token.partition(":")
        if not email or not api_token:
            raise ConnectorValidationError(
                "Confluence credential must be 'email:api_token' (colon-separated)"
            )
        return email, api_token

    def test_connection(self, config: dict, access_token: str) -> dict:
        base_url, space_key = _normalise_config(config)
        email, api_token = self._split_credential(access_token)

        resp = _confluence_request(
            "GET", f"{base_url}/wiki/rest/api/space/{space_key}", email, api_token
        )
        if resp.status_code in (401, 403):
            raise ConnectorValidationError(
                "Confluence rejected the credential — the email/API token is invalid, "
                "expired, or lacks access to this space"
            )
        if resp.status_code == 404:
            raise ConnectorValidationError(f"Space '{space_key}' was not found or is not accessible")
        if resp.status_code != 200:
            raise ConnectorValidationError(
                f"Confluence API returned HTTP {resp.status_code} while validating the connection"
            )
        data = resp.json()
        return {
            "base_url": base_url,
            "space_key": space_key,
            "space_name": data.get("name", space_key),
        }

    def _fetch_pages(self, base_url: str, space_key: str, email: str, api_token: str) -> list[dict]:
        pages: list[dict] = []
        start = 0
        while True:
            resp = _confluence_request(
                "GET",
                f"{base_url}/wiki/rest/api/content",
                email,
                api_token,
                params={
                    "spaceKey": space_key,
                    "type": "page",
                    "start": start,
                    "limit": PAGE_SIZE,
                    "expand": "body.storage,version",
                },
            )
            if resp.status_code == 401:
                raise ConnectorValidationError("Confluence rejected the credential during sync")
            if resp.status_code != 200:
                raise ConnectorSyncError(f"Confluence could not list pages (HTTP {resp.status_code})")
            data = resp.json()
            batch = data.get("results", []) or []
            pages.extend(batch)
            if len(batch) < PAGE_SIZE:
                break
            start += len(batch)
        return pages

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
        base_url, space_key = validated["base_url"], validated["space_key"]
        email, api_token = self._split_credential(access_token)

        engine = engine or get_sync_engine()
        Base.metadata.create_all(engine, checkfirst=True)

        pages = self._fetch_pages(base_url, space_key, email, api_token)
        collection_name = workspace_collection_name(workspace_id)
        result = ConnectorSyncResult()

        with Session(engine) as db:
            for page in pages:
                title = page.get("title", "")
                page_id = page.get("id", "")
                html = ((page.get("body") or {}).get("storage") or {}).get("value", "")
                body = _strip_html(html)
                version = (page.get("version") or {}).get("number", 1)
                identity = f"confluence://{base_url}/{space_key}/{page_id}"
                checksum = hashlib.sha256(f"{version}:{body}".encode("utf-8")).hexdigest()

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
                        f"Embedding/index infrastructure failed for '{title}': {type(exc).__name__}: {exc}"
                    ) from exc

                if doc is None:
                    doc = Document(
                        title=title[:255],
                        content_type="text/plain",
                        status="PROCESSING",
                        source_url=f"{base_url}/wiki/spaces/{space_key}/pages/{page_id}",
                        file_path=identity,
                        workspace_id=workspace_id,
                        uploaded_by=uploaded_by,
                        metadata_json={
                            "connector": self.provider,
                            "space_key": space_key,
                            "page_id": page_id,
                            "source": "confluence",
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
                            collection_name, doc.id, chunks, embeddings,
                            organization_id=organization_id, workspace_id=workspace_id,
                        )
                        if chunks else 0
                    )
                except Exception as exc:  # noqa: BLE001
                    db.rollback()
                    raise ConnectorSyncError(
                        f"Failed to index '{title}' into the vector store: {type(exc).__name__}: {exc}"
                    ) from exc

                db.add(
                    DocumentVersion(
                        document_id=doc.id, version=version_number, file_path=identity,
                        checksum=checksum, status="INDEXED", uploaded_by=uploaded_by,
                    )
                )
                doc.status = "INDEXED"
                doc.chunk_count = chunk_count
                result.files_processed += 1
                result.chunk_count += chunk_count
                result.details.append(f"{title}: indexed {chunk_count} chunks (v{version_number})")

            db.commit()

        result.details.insert(
            0,
            f"space={space_key} pages={len(pages)} created={result.files_created} "
            f"skipped={result.files_skipped} failed={result.files_failed} chunks={result.chunk_count}",
        )
        return result

    def health_check(self, config: dict, access_token: str, connector_status: dict) -> ConnectorHealth:
        base_url, space_key = _normalise_config(config)
        try:
            email, api_token = self._split_credential(access_token)
            resp = _confluence_request(
                "GET", f"{base_url}/wiki/rest/api/space/{space_key}", email, api_token
            )
        except (httpx.HTTPError, ConnectorValidationError) as exc:
            return ConnectorHealth(
                token_valid=False,
                detail=f"Confluence unreachable: {type(exc).__name__}: {exc}",
                last_sync_status=connector_status.get("last_sync_status"),
                last_sync_error=connector_status.get("last_sync_error"),
                last_sync_at=connector_status.get("last_sync_at"),
            )

        if resp.status_code == 200:
            data = resp.json()
            return ConnectorHealth(
                token_valid=True,
                detail=f"Token valid, space '{data.get('name', space_key)}' accessible",
                last_sync_status=connector_status.get("last_sync_status"),
                last_sync_error=connector_status.get("last_sync_error"),
                last_sync_at=connector_status.get("last_sync_at"),
            )
        if resp.status_code in (401, 403):
            return ConnectorHealth(
                token_valid=False,
                detail="Stored credential is invalid, expired, or revoked",
                last_sync_status=connector_status.get("last_sync_status"),
                last_sync_error=connector_status.get("last_sync_error"),
                last_sync_at=connector_status.get("last_sync_at"),
            )
        return ConnectorHealth(
            token_valid=False,
            detail=f"Credential check failed (HTTP {resp.status_code})",
            last_sync_status=connector_status.get("last_sync_status"),
            last_sync_error=connector_status.get("last_sync_error"),
            last_sync_at=connector_status.get("last_sync_at"),
        )

    def identity_key(self, validated_config: dict) -> str | None:
        space_key = validated_config.get("space_key")
        return space_key.lower() if space_key else None
