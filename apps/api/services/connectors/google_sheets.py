"""Google Sheets connector: OAuth2 install (with refresh), sync sheet data.

Implements :class:`ConnectorAdapter` with ``auth_type = "oauth2"``. Reuses
the same Google OAuth2 app as Drive/Calendar, its own minimal scope
(``spreadsheets.readonly`` + ``drive.readonly`` to discover which sheets
exist) in its own separate authorization flow.
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

DRIVE_API = "https://www.googleapis.com/drive/v3"
SHEETS_API = "https://sheets.googleapis.com/v4"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DEFAULT_TIMEOUT = httpx.Timeout(30.0)
SHEET_MIME = "application/vnd.google-apps.spreadsheet"


def _sheets_request(method: str, url: str, access_token: str, **kwargs: Any) -> httpx.Response:
    headers = {"Authorization": f"Bearer {access_token}"}
    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        return client.request(method, url, headers=headers, **kwargs)


class GoogleSheetsConnector(ConnectorAdapter):
    """Adapter for a Google Sheets account connected via OAuth2."""

    provider = "google_sheets"
    auth_type = "oauth2"

    def oauth_authorize_url(self, state: str, *, workspace_id: str) -> str:
        settings = get_settings()
        scope = (
            "https://www.googleapis.com/auth/spreadsheets.readonly "
            "https://www.googleapis.com/auth/drive.readonly"
        )
        return (
            "https://accounts.google.com/o/oauth2/v2/auth"
            f"?client_id={settings.GOOGLE_DRIVE_CLIENT_ID}"
            f"&redirect_uri={settings.GOOGLE_SHEETS_OAUTH_REDIRECT_URI}"
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
                    "redirect_uri": settings.GOOGLE_SHEETS_OAUTH_REDIRECT_URI,
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
            refresh_token=refresh_token,
            expires_in=data.get("expires_in"),
        )

    def test_connection(self, config: dict, access_token: str) -> dict:
        resp = _sheets_request(
            "GET", f"{DRIVE_API}/about", access_token, params={"fields": "user"}
        )
        if resp.status_code == 401:
            raise ConnectorValidationError(
                "Google rejected the access token — it is invalid or expired"
            )
        if resp.status_code != 200:
            raise ConnectorValidationError(
                f"Google API returned HTTP {resp.status_code} while validating the connection"
            )
        data = resp.json()
        return {"account": (data.get("user") or {}).get("emailAddress", "")}

    def _list_sheets(self, access_token: str) -> list[dict]:
        resp = _sheets_request(
            "GET",
            f"{DRIVE_API}/files",
            access_token,
            params={"q": f"mimeType='{SHEET_MIME}' and trashed=false", "fields": "files(id,name)"},
        )
        if resp.status_code != 200:
            raise ConnectorSyncError(f"Could not list spreadsheets (HTTP {resp.status_code})")
        return resp.json().get("files", [])

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

        sheets = self._list_sheets(access_token)
        engine = engine or get_sync_engine()
        Base.metadata.create_all(engine, checkfirst=True)
        collection_name = workspace_collection_name(workspace_id)
        result = ConnectorSyncResult()

        with Session(engine) as db:
            for sheet in sheets:
                sheet_id, name = sheet["id"], sheet.get("name", sheet["id"])
                resp = _sheets_request(
                    "GET",
                    f"{SHEETS_API}/spreadsheets/{sheet_id}/values/A1:Z1000",
                    access_token,
                )
                if resp.status_code != 200:
                    result.files_failed += 1
                    result.details.append(f"{name}: HTTP {resp.status_code}")
                    continue
                rows = resp.json().get("values", [])
                body = "\n".join(", ".join(str(c) for c in row) for row in rows)

                identity = f"gsheets://{sheet_id}"
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
                embeddings = generate_embeddings(chunks) if chunks else []
                vector_size = len(embeddings[0]) if embeddings else 384
                ensure_collection(collection_name, vector_size=vector_size)

                if doc is None:
                    doc = Document(
                        title=name[:255],
                        content_type="text/csv",
                        status="PROCESSING",
                        source_url=f"https://docs.google.com/spreadsheets/d/{sheet_id}",
                        file_path=identity,
                        workspace_id=workspace_id,
                        uploaded_by=uploaded_by,
                        metadata_json={"connector": self.provider, "sheet_id": sheet_id, "source": "google_sheets"},
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

                chunk_count = (
                    index_chunks(
                        collection_name, doc.id, chunks, embeddings,
                        organization_id=organization_id, workspace_id=workspace_id,
                    )
                    if chunks else 0
                )
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
                result.details.append(f"{name}: {len(rows)} rows, {chunk_count} chunks")

            db.commit()

        result.details.insert(0, f"sheets={len(sheets)} created={result.files_created} skipped={result.files_skipped} failed={result.files_failed}")
        return result

    def health_check(self, config: dict, access_token: str, connector_status: dict) -> ConnectorHealth:
        try:
            resp = _sheets_request(
                "GET", f"{DRIVE_API}/about", access_token, params={"fields": "user"}
            )
        except httpx.HTTPError as exc:
            return ConnectorHealth(
                token_valid=False,
                detail=f"Google Sheets unreachable: {type(exc).__name__}",
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
