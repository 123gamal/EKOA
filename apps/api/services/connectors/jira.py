"""Jira connector: connect/validate, sync a project's issues, health check.

Implements :class:`ConnectorAdapter` for a Jira Cloud project using an API
token (HTTP Basic auth: ``email:api_token``, same auth model Atlassian's REST
API v3 expects). Same lazy-import pattern as the GitHub connector so this
module stays importable from the API service (no worker-only deps at
import time).
"""

from __future__ import annotations

import base64
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

DEFAULT_TIMEOUT = httpx.Timeout(30.0)
PAGE_SIZE = 50


def _normalise_config(config: dict) -> tuple[str, str]:
    base_url = (config.get("base_url") or "").strip().rstrip("/")
    project_key = (config.get("project_key") or "").strip().upper()
    if not base_url or not project_key:
        raise ConnectorValidationError("Jira config requires 'base_url' and 'project_key'")
    return base_url, project_key


def _basic_auth_header(email: str, api_token: str) -> str:
    raw = f"{email}:{api_token}".encode("utf-8")
    return f"Basic {base64.b64encode(raw).decode('ascii')}"


def _jira_request(
    method: str,
    url: str,
    email: str,
    api_token: str,
    **kwargs: Any,
) -> httpx.Response:
    """Perform a Jira REST API call with Basic auth. Module-level so tests
    can monkeypatch a single seam, same pattern as GitHub's connector."""
    headers = {
        "Accept": "application/json",
        "Authorization": _basic_auth_header(email, api_token),
    }
    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        return client.request(method, url, headers=headers, **kwargs)


class JiraConnector(ConnectorAdapter):
    """Adapter for a Jira Cloud project connected with an email + API token.

    The "access_token" this adapter receives is actually ``email:api_token``
    joined by a colon (the connect form collects both, joins them before
    calling into the generic ConnectorAdapter interface which only has one
    secret slot) — see ``_split_credential``.
    """

    provider = "jira"

    @staticmethod
    def _split_credential(access_token: str) -> tuple[str, str]:
        if ":" not in access_token:
            raise ConnectorValidationError(
                "Jira credential must be 'email:api_token' (colon-separated)"
            )
        email, _, api_token = access_token.partition(":")
        if not email or not api_token:
            raise ConnectorValidationError(
                "Jira credential must be 'email:api_token' (colon-separated)"
            )
        return email, api_token

    def test_connection(self, config: dict, access_token: str) -> dict:
        """Validate the API token against Jira and confirm the project exists."""
        base_url, project_key = _normalise_config(config)
        email, api_token = self._split_credential(access_token)

        resp = _jira_request("GET", f"{base_url}/rest/api/3/myself", email, api_token)
        if resp.status_code in (401, 403):
            raise ConnectorValidationError(
                "Jira rejected the credential — the email/API token is invalid, "
                "expired, or revoked"
            )
        if resp.status_code != 200:
            raise ConnectorValidationError(
                f"Jira API returned HTTP {resp.status_code} while validating the credential"
            )

        proj_resp = _jira_request(
            "GET", f"{base_url}/rest/api/3/project/{project_key}", email, api_token
        )
        if proj_resp.status_code == 404:
            raise ConnectorValidationError(
                f"Project '{project_key}' was not found or is not accessible with this account"
            )
        if proj_resp.status_code != 200:
            raise ConnectorValidationError(
                f"Jira API returned HTTP {proj_resp.status_code} while validating the project"
            )
        proj = proj_resp.json()
        return {
            "base_url": base_url,
            "project_key": project_key,
            "project_name": proj.get("name", project_key),
        }

    def _adf_to_text(self, node: Any) -> str:
        """Flatten Jira's Atlassian Document Format (rich text) to plain text."""
        if node is None:
            return ""
        if isinstance(node, str):
            return node
        if isinstance(node, list):
            return "\n".join(self._adf_to_text(n) for n in node)
        if isinstance(node, dict):
            if node.get("type") == "text":
                return node.get("text", "")
            return "\n".join(self._adf_to_text(c) for c in node.get("content", []) or [])
        return ""

    def _fetch_issues(self, base_url: str, project_key: str, email: str, api_token: str) -> list[dict]:
        """Search issues via Jira's "Enhanced JQL" endpoint.

        The classic ``GET /rest/api/3/search`` (offset/``startAt`` paginated,
        returned a ``total`` count) was removed by Atlassian — confirmed live
        against a real Jira Cloud site during this phase's verification,
        returning HTTP 410 Gone. The replacement,
        ``GET /rest/api/3/search/jql``, uses cursor-based pagination via
        ``nextPageToken`` instead and does not reliably report a total count,
        so pagination here just continues until a page comes back without a
        token (or empty).
        """
        issues: list[dict] = []
        next_page_token: str | None = None
        while True:
            params: dict = {
                "jql": f"project={project_key} ORDER BY updated DESC",
                "maxResults": PAGE_SIZE,
                "fields": "summary,description,updated,comment",
            }
            if next_page_token:
                params["nextPageToken"] = next_page_token
            resp = _jira_request(
                "GET",
                f"{base_url}/rest/api/3/search/jql",
                email,
                api_token,
                params=params,
            )
            if resp.status_code == 401:
                raise ConnectorValidationError(
                    "Jira rejected the credential during sync — invalid, expired, or revoked"
                )
            if resp.status_code != 200:
                raise ConnectorSyncError(
                    f"Jira could not search issues (HTTP {resp.status_code})"
                )
            data = resp.json()
            batch = data.get("issues", []) or []
            issues.extend(batch)
            next_page_token = data.get("nextPageToken")
            if not batch or not next_page_token:
                break
        return issues

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
        """Fetch the project's issues and index them as deduped Documents."""
        from apps.api.models.document import Document
        from apps.api.models.document_version import DocumentVersion
        from apps.api.db.base import Base
        from apps.worker.chunking import chunk_text
        from apps.worker.embeddings import ensure_collection, generate_embeddings, index_chunks
        from apps.worker.workflow_executor import get_sync_engine
        from ekoa_utils.naming import workspace_collection_name
        from sqlalchemy.orm import Session

        validated = self.test_connection(config, access_token)
        base_url, project_key = validated["base_url"], validated["project_key"]
        email, api_token = self._split_credential(access_token)

        engine = engine or get_sync_engine()
        Base.metadata.create_all(engine, checkfirst=True)

        issues = self._fetch_issues(base_url, project_key, email, api_token)
        collection_name = workspace_collection_name(workspace_id)
        result = ConnectorSyncResult()

        with Session(engine) as db:
            for issue in issues:
                key = issue.get("key", "")
                fields = issue.get("fields", {}) or {}
                summary = fields.get("summary", "") or ""
                description = self._adf_to_text(fields.get("description"))
                comments = fields.get("comment", {}).get("comments", []) or []
                comment_text = "\n\n".join(
                    self._adf_to_text(c.get("body")) for c in comments
                )
                body = f"{summary}\n\n{description}\n\n{comment_text}".strip()
                identity = f"jira://{base_url}/{key}"
                checksum = hashlib.sha256(
                    f"{fields.get('updated', '')}:{body}".encode("utf-8")
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

                chunks = chunk_text(body) if body else []
                try:
                    embeddings = generate_embeddings(chunks) if chunks else []
                    vector_size = len(embeddings[0]) if embeddings else 384
                    ensure_collection(collection_name, vector_size=vector_size)
                except Exception as exc:  # noqa: BLE001
                    db.rollback()
                    raise ConnectorSyncError(
                        f"Embedding/index infrastructure failed for '{key}': "
                        f"{type(exc).__name__}: {exc}"
                    ) from exc

                if doc is None:
                    doc = Document(
                        title=f"{key}: {summary}"[:255],
                        content_type="text/plain",
                        status="PROCESSING",
                        source_url=f"{base_url}/browse/{key}",
                        file_path=identity,
                        workspace_id=workspace_id,
                        uploaded_by=uploaded_by,
                        metadata_json={
                            "connector": self.provider,
                            "project_key": project_key,
                            "issue_key": key,
                            "source": "jira",
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
                        f"Failed to index '{key}' into the vector store: "
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
                result.details.append(f"{key}: indexed {chunk_count} chunks (v{version_number})")

            db.commit()

        result.details.insert(
            0,
            f"project={project_key} issues={len(issues)} created={result.files_created} "
            f"skipped={result.files_skipped} failed={result.files_failed} chunks={result.chunk_count}",
        )
        return result

    def health_check(self, config: dict, access_token: str, connector_status: dict) -> ConnectorHealth:
        base_url, project_key = _normalise_config(config)
        try:
            email, api_token = self._split_credential(access_token)
            resp = _jira_request("GET", f"{base_url}/rest/api/3/myself", email, api_token)
        except (httpx.HTTPError, ConnectorValidationError) as exc:
            return ConnectorHealth(
                token_valid=False,
                detail=f"Jira unreachable: {type(exc).__name__}: {exc}",
                last_sync_status=connector_status.get("last_sync_status"),
                last_sync_error=connector_status.get("last_sync_error"),
                last_sync_at=connector_status.get("last_sync_at"),
            )

        if resp.status_code == 200:
            data = resp.json()
            return ConnectorHealth(
                token_valid=True,
                detail=f"Token valid, authenticated as '{data.get('displayName', 'unknown')}'",
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
        project_key = validated_config.get("project_key")
        return project_key.lower() if project_key else None
