"""Google Drive connector: OAuth2 install (with refresh), sync Google Docs.

Implements :class:`ConnectorAdapter` with ``auth_type = "oauth2"``. Unlike
Slack's bot token, Google's access tokens expire (~1hr) — this is the one
adapter that actually uses :class:`~apps.api.models.connector.
ConnectorCredential`'s ``refresh_token_encrypted``/``token_expires_at``
columns, refreshing before any API call via ``_ensure_fresh_token`` (called
by the ``sync``/``health_check`` call sites in ``apps/api/routes/connectors.py``
and the worker task, which pass the live credential row so the refreshed
token can be persisted back).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
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

DRIVE_API = "https://www.googleapis.com/drive/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DEFAULT_TIMEOUT = httpx.Timeout(30.0)
DOC_MIME = "application/vnd.google-apps.document"


def _drive_request(method: str, url: str, access_token: str, **kwargs: Any) -> httpx.Response:
    headers = {"Authorization": f"Bearer {access_token}"}
    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        return client.request(method, url, headers=headers, **kwargs)


class GoogleDriveConnector(ConnectorAdapter):
    """Adapter for a Google Drive account connected via OAuth2."""

    provider = "google_drive"
    auth_type = "oauth2"

    def oauth_authorize_url(self, state: str, *, workspace_id: str) -> str:
        settings = get_settings()
        scope = "https://www.googleapis.com/auth/drive.readonly"
        return (
            "https://accounts.google.com/o/oauth2/v2/auth"
            f"?client_id={settings.GOOGLE_DRIVE_CLIENT_ID}"
            f"&redirect_uri={settings.GOOGLE_DRIVE_OAUTH_REDIRECT_URI}"
            "&response_type=code"
            f"&scope={scope}"
            "&access_type=offline"
            "&prompt=consent"
            f"&state={state}"
        )

    def oauth_exchange_code(self, code: str) -> OAuthTokenResult:
        settings = get_settings()
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            resp = client.post(
                TOKEN_URL,
                data={
                    "client_id": settings.GOOGLE_DRIVE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_DRIVE_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": settings.GOOGLE_DRIVE_OAUTH_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
            )
        data = resp.json()
        if "access_token" not in data:
            raise ConnectorValidationError(
                f"Google OAuth exchange failed: {data.get('error_description', data.get('error', 'unknown_error'))}"
            )
        return OAuthTokenResult(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_in=data.get("expires_in"),
            config={},
        )

    def refresh_access_token(self, refresh_token: str) -> OAuthTokenResult:
        settings = get_settings()
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            resp = client.post(
                TOKEN_URL,
                data={
                    "client_id": settings.GOOGLE_DRIVE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_DRIVE_CLIENT_SECRET,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        data = resp.json()
        if "access_token" not in data:
            raise ConnectorValidationError(
                f"Google token refresh failed: {data.get('error_description', data.get('error', 'unknown_error'))}"
            )
        return OAuthTokenResult(
            access_token=data["access_token"],
            refresh_token=refresh_token,  # Google doesn't rotate it on refresh
            expires_in=data.get("expires_in"),
        )

    def test_connection(self, config: dict, access_token: str) -> dict:
        resp = _drive_request("GET", f"{DRIVE_API}/about", access_token, params={"fields": "user"})
        if resp.status_code == 401:
            raise ConnectorValidationError(
                "Google rejected the access token — it is invalid or expired"
            )
        if resp.status_code != 200:
            raise ConnectorValidationError(
                f"Google Drive API returned HTTP {resp.status_code} while validating the connection"
            )
        data = resp.json()
        user_email = (data.get("user") or {}).get("emailAddress", "")
        return {"folder_id": config.get("folder_id"), "account": user_email}

    def _list_docs(self, access_token: str, folder_id: str | None) -> list[dict]:
        files: list[dict] = []
        page_token = None
        q = f"mimeType='{DOC_MIME}' and trashed=false"
        if folder_id:
            q += f" and '{folder_id}' in parents"
        while True:
            params: dict[str, Any] = {
                "q": q,
                "fields": "nextPageToken, files(id, name, modifiedTime)",
                "pageSize": 100,
            }
            if page_token:
                params["pageToken"] = page_token
            resp = _drive_request("GET", f"{DRIVE_API}/files", access_token, params=params)
            if resp.status_code == 401:
                raise ConnectorValidationError("Google rejected the access token during sync")
            if resp.status_code != 200:
                raise ConnectorSyncError(
                    f"Google Drive could not list files (HTTP {resp.status_code})"
                )
            data = resp.json()
            files.extend(data.get("files", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return files

    def _export_text(self, file_id: str, access_token: str) -> str:
        resp = _drive_request(
            "GET",
            f"{DRIVE_API}/files/{file_id}/export",
            access_token,
            params={"mimeType": "text/plain"},
        )
        if resp.status_code != 200:
            raise ConnectorSyncError(
                f"Google Drive could not export '{file_id}' (HTTP {resp.status_code})"
            )
        return resp.text

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
        """Fetch Google Docs (optionally scoped to a folder) and index as Documents."""
        from apps.api.models.document import Document
        from apps.api.models.document_version import DocumentVersion
        from apps.api.db.base import Base
        from apps.worker.chunking import chunk_text
        from apps.worker.embeddings import ensure_collection, generate_embeddings, index_chunks
        from apps.worker.workflow_executor import get_sync_engine
        from ekoa_utils.naming import workspace_collection_name
        from sqlalchemy.orm import Session

        folder_id = config.get("folder_id")
        files = self._list_docs(access_token, folder_id)

        engine = engine or get_sync_engine()
        Base.metadata.create_all(engine, checkfirst=True)

        collection_name = workspace_collection_name(workspace_id)
        result = ConnectorSyncResult()

        with Session(engine) as db:
            for f in files:
                file_id, name = f["id"], f.get("name", f["id"])
                try:
                    text = self._export_text(file_id, access_token)
                except ConnectorSyncError as exc:
                    result.files_failed += 1
                    result.details.append(f"{name}: {exc}")
                    logger.warning("Drive sync file failed %s: %s", file_id, exc)
                    continue

                identity = f"gdrive://{file_id}"
                checksum = hashlib.sha256(
                    f"{f.get('modifiedTime', '')}:{text}".encode("utf-8")
                ).hexdigest()

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

                chunks = chunk_text(text) if text else []
                try:
                    embeddings = generate_embeddings(chunks) if chunks else []
                    vector_size = len(embeddings[0]) if embeddings else 384
                    ensure_collection(collection_name, vector_size=vector_size)
                except Exception as exc:  # noqa: BLE001
                    db.rollback()
                    raise ConnectorSyncError(
                        f"Embedding/index infrastructure failed for '{name}': "
                        f"{type(exc).__name__}: {exc}"
                    ) from exc

                if doc is None:
                    doc = Document(
                        title=name[:255],
                        content_type="text/plain",
                        status="PROCESSING",
                        source_url=f"https://docs.google.com/document/d/{file_id}",
                        file_path=identity,
                        workspace_id=workspace_id,
                        uploaded_by=uploaded_by,
                        metadata_json={
                            "connector": self.provider,
                            "file_id": file_id,
                            "source": "google_drive",
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
                        f"Failed to index '{name}' into the vector store: "
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
                result.details.append(f"{name}: indexed {chunk_count} chunks (v{version_number})")

            db.commit()

        result.details.insert(
            0,
            f"folder={folder_id or 'all'} files={len(files)} created={result.files_created} "
            f"skipped={result.files_skipped} failed={result.files_failed} chunks={result.chunk_count}",
        )
        return result

    def health_check(self, config: dict, access_token: str, connector_status: dict) -> ConnectorHealth:
        try:
            resp = _drive_request(
                "GET", f"{DRIVE_API}/about", access_token, params={"fields": "user"}
            )
        except httpx.HTTPError as exc:
            return ConnectorHealth(
                token_valid=False,
                detail=f"Google Drive unreachable: {type(exc).__name__}",
                last_sync_status=connector_status.get("last_sync_status"),
                last_sync_error=connector_status.get("last_sync_error"),
                last_sync_at=connector_status.get("last_sync_at"),
            )

        if resp.status_code == 200:
            data = resp.json()
            account = (data.get("user") or {}).get("emailAddress", "unknown")
            return ConnectorHealth(
                token_valid=True,
                detail=f"Token valid for account '{account}'",
                last_sync_status=connector_status.get("last_sync_status"),
                last_sync_error=connector_status.get("last_sync_error"),
                last_sync_at=connector_status.get("last_sync_at"),
            )
        if resp.status_code == 401:
            return ConnectorHealth(
                token_valid=False,
                detail="Stored access token is invalid or expired (refresh may be needed)",
                last_sync_status=connector_status.get("last_sync_status"),
                last_sync_error=connector_status.get("last_sync_error"),
                last_sync_at=connector_status.get("last_sync_at"),
            )
        return ConnectorHealth(
            token_valid=False,
            detail=f"Account check failed (HTTP {resp.status_code})",
            last_sync_status=connector_status.get("last_sync_status"),
            last_sync_error=connector_status.get("last_sync_error"),
            last_sync_at=connector_status.get("last_sync_at"),
        )

    def identity_key(self, validated_config: dict) -> str | None:
        return validated_config.get("account")


def token_expired(expires_at: datetime | None) -> bool:
    """True when a stored access token's expiry has passed (or is unset —
    treated as expired so a fresh refresh is always attempted defensively)."""
    if expires_at is None:
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    # 60s safety margin so a token doesn't expire mid-request.
    return expires_at <= datetime.now(timezone.utc) + timedelta(seconds=60)
