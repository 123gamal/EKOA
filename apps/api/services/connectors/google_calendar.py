"""Google Calendar connector: OAuth2 install (with refresh), sync events.

Implements :class:`ConnectorAdapter` with ``auth_type = "oauth2"``. Reuses
the same Google OAuth2 app (``GOOGLE_DRIVE_CLIENT_ID``/``_SECRET``) as the
Google Drive connector — each connector requests its own minimal scope in
its own separate authorization flow, so a Calendar-connector token can never
read Drive files and vice versa, even though they share one registered app.
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

CALENDAR_API = "https://www.googleapis.com/calendar/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DEFAULT_TIMEOUT = httpx.Timeout(30.0)


def _calendar_request(method: str, url: str, access_token: str, **kwargs: Any) -> httpx.Response:
    headers = {"Authorization": f"Bearer {access_token}"}
    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        return client.request(method, url, headers=headers, **kwargs)


class GoogleCalendarConnector(ConnectorAdapter):
    """Adapter for a Google Calendar account connected via OAuth2."""

    provider = "google_calendar"
    auth_type = "oauth2"

    def oauth_authorize_url(self, state: str, *, workspace_id: str) -> str:
        settings = get_settings()
        scope = "https://www.googleapis.com/auth/calendar.readonly"
        return (
            "https://accounts.google.com/o/oauth2/v2/auth"
            f"?client_id={settings.GOOGLE_DRIVE_CLIENT_ID}"
            f"&redirect_uri={settings.GOOGLE_CALENDAR_OAUTH_REDIRECT_URI}"
            "&response_type=code"
            f"&scope={scope}"
            "&access_type=offline"
            "&prompt=consent"
            f"&state={state}"
        )

    def oauth_exchange_code(self, code: str) -> OAuthTokenResult:
        settings = get_settings()
        redirect_uri = settings.GOOGLE_CALENDAR_OAUTH_REDIRECT_URI
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            resp = client.post(
                TOKEN_URL,
                data={
                    "client_id": settings.GOOGLE_DRIVE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_DRIVE_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": redirect_uri,
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
        resp = _calendar_request(
            "GET", f"{CALENDAR_API}/calendars/primary", access_token
        )
        if resp.status_code == 401:
            raise ConnectorValidationError(
                "Google rejected the access token — it is invalid or expired"
            )
        if resp.status_code != 200:
            raise ConnectorValidationError(
                f"Google Calendar API returned HTTP {resp.status_code} while validating the connection"
            )
        data = resp.json()
        return {"calendar_id": "primary", "account": data.get("id", "")}

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
        """Fetch recent/upcoming events and roll them into one 'calendar
        digest' Document (a per-event Document each would be a lot of tiny,
        low-value documents for a knowledge base — a single rolled-up
        summary is both simpler and more useful to retrieve)."""
        from apps.api.models.document import Document
        from apps.api.models.document_version import DocumentVersion
        from apps.api.db.base import Base
        from apps.worker.chunking import chunk_text
        from apps.worker.embeddings import ensure_collection, generate_embeddings, index_chunks
        from apps.worker.workflow_executor import get_sync_engine
        from ekoa_utils.naming import workspace_collection_name
        from sqlalchemy.orm import Session

        resp = _calendar_request(
            "GET",
            f"{CALENDAR_API}/calendars/primary/events",
            access_token,
            params={
                "maxResults": 100,
                "singleEvents": "true",
                "orderBy": "startTime",
                "timeMin": "2020-01-01T00:00:00Z",
            },
        )
        if resp.status_code == 401:
            raise ConnectorValidationError("Google rejected the access token during sync")
        if resp.status_code != 200:
            raise ConnectorSyncError(
                f"Google Calendar could not list events (HTTP {resp.status_code})"
            )
        events = resp.json().get("items", [])

        lines = []
        for ev in events:
            summary = ev.get("summary", "(no title)")
            start = (ev.get("start") or {}).get("dateTime") or (ev.get("start") or {}).get("date", "")
            attendees = ", ".join(a.get("email", "") for a in ev.get("attendees", []) or [])
            description = ev.get("description", "")
            lines.append(f"- {start} — {summary}" + (f" (attendees: {attendees})" if attendees else "") + (f"\n  {description}" if description else ""))
        body = "Calendar digest:\n\n" + ("\n".join(lines) if lines else "No events found.")

        engine = engine or get_sync_engine()
        Base.metadata.create_all(engine, checkfirst=True)
        collection_name = workspace_collection_name(workspace_id)
        result = ConnectorSyncResult()

        identity = "gcalendar://primary/digest"
        checksum = hashlib.sha256(body.encode("utf-8")).hexdigest()

        with Session(engine) as db:
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
                result.details.append(f"digest unchanged, events={len(events)}")
                return result

            chunks = chunk_text(body) if body else []
            embeddings = generate_embeddings(chunks) if chunks else []
            vector_size = len(embeddings[0]) if embeddings else 384
            ensure_collection(collection_name, vector_size=vector_size)

            if doc is None:
                doc = Document(
                    title="Google Calendar digest",
                    content_type="text/plain",
                    status="PROCESSING",
                    source_url="https://calendar.google.com/",
                    file_path=identity,
                    workspace_id=workspace_id,
                    uploaded_by=uploaded_by,
                    metadata_json={"connector": self.provider, "source": "google_calendar"},
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
            result.details.append(f"events={len(events)} chunks={chunk_count}")
            db.commit()

        return result

    def health_check(self, config: dict, access_token: str, connector_status: dict) -> ConnectorHealth:
        try:
            resp = _calendar_request("GET", f"{CALENDAR_API}/calendars/primary", access_token)
        except httpx.HTTPError as exc:
            return ConnectorHealth(
                token_valid=False,
                detail=f"Google Calendar unreachable: {type(exc).__name__}",
                last_sync_status=connector_status.get("last_sync_status"),
                last_sync_error=connector_status.get("last_sync_error"),
                last_sync_at=connector_status.get("last_sync_at"),
            )
        if resp.status_code == 200:
            return ConnectorHealth(
                token_valid=True,
                detail="Token valid, calendar accessible",
                last_sync_status=connector_status.get("last_sync_status"),
                last_sync_error=connector_status.get("last_sync_error"),
                last_sync_at=connector_status.get("last_sync_at"),
            )
        return ConnectorHealth(
            token_valid=False,
            detail=f"Calendar check failed (HTTP {resp.status_code})",
            last_sync_status=connector_status.get("last_sync_status"),
            last_sync_error=connector_status.get("last_sync_error"),
            last_sync_at=connector_status.get("last_sync_at"),
        )

    def identity_key(self, validated_config: dict) -> str | None:
        return validated_config.get("account")
