"""GitHub connector: connect/validate, sync README + docs/**/*.md, health check.

Implements :class:`ConnectorAdapter` for GitHub repositories using a classic
PAT. The token is only ever held in memory here; the API encrypts it before
persisting (Fernet) and the worker decrypts it for the duration of a sync.

Heavy worker-only dependencies (sentence-transformers, qdrant-client) are
imported lazily inside :meth:`GitHubConnector.sync` so this module stays safe
to import from the API service (which has none of them installed).
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

GITHUB_API = "https://api.github.com"
DEFAULT_TIMEOUT = httpx.Timeout(30.0)


def _github_request(
    method: str,
    url: str,
    access_token: str,
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> httpx.Response:
    """Perform a GitHub REST API call with auth + API-version headers.

    Kept as a module-level helper so tests can monkeypatch a single seam.
    """
    req_headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {access_token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if headers:
        req_headers.update(headers)
    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        return client.request(method, url, headers=req_headers, **kwargs)


def _normalise_config(config: dict) -> tuple[str, str]:
    owner = (config.get("owner") or "").strip().lower()
    repo = (config.get("repo") or "").strip().lower()
    if not owner or not repo:
        raise ConnectorValidationError("GitHub config requires 'owner' and 'repo'")
    return owner, repo


class GitHubConnector(ConnectorAdapter):
    """Adapter for a GitHub repository connected with a classic PAT."""

    provider = "github"

    def test_connection(self, config: dict, access_token: str) -> dict:
        """Validate the PAT and repo against the GitHub API before saving."""
        owner, repo = _normalise_config(config)
        resp = _github_request("GET", f"{GITHUB_API}/repos/{owner}/{repo}", access_token)
        if resp.status_code in (401, 403):
            raise ConnectorValidationError(
                "GitHub rejected the token — it is invalid, expired, revoked, "
                "or lacks permission to access this repository"
            )
        if resp.status_code == 404:
            raise ConnectorValidationError(
                f"Repository '{owner}/{repo}' was not found or is private / "
                "not accessible with this token"
            )
        if resp.status_code != 200:
            raise ConnectorValidationError(
                f"GitHub API returned HTTP {resp.status_code} while validating the connection"
            )
        data = resp.json()
        return {
            "owner": owner,
            "repo": repo,
            "full_name": data.get("full_name", f"{owner}/{repo}"),
            "default_branch": data.get("default_branch", "main"),
            "private": data.get("private", False),
        }

    def _repo_tree_files(self, config: dict, access_token: str, branch: str) -> list[str]:
        owner, repo = _normalise_config(config)
        url = f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
        resp = _github_request("GET", url, access_token)
        if resp.status_code == 401:
            raise ConnectorValidationError(
                "GitHub rejected the token during sync — it is invalid, expired, or revoked"
            )
        if resp.status_code != 200:
            raise ConnectorSyncError(
                f"GitHub could not list the repository tree (HTTP {resp.status_code})"
            )
        data = resp.json()
        tree = data.get("tree", []) or []
        paths: list[str] = []
        for entry in tree:
            if entry.get("type") != "blob":
                continue
            path = entry.get("path") or ""
            # V1 scope: repo README + all markdown under docs/.
            path_lower = path.lower()
            is_readme = path_lower == "readme.md" or path_lower == "readme"
            is_docs_md = path_lower.startswith("docs/") and path_lower.endswith(".md")
            if is_readme or is_docs_md:
                paths.append(path)
        return sorted(set(paths))

    def _fetch_raw(self, config: dict, access_token: str, path: str) -> bytes:
        owner, repo = _normalise_config(config)
        url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}"
        resp = _github_request(
            "GET",
            url,
            access_token,
            headers={"Accept": "application/vnd.github.raw"},
        )
        if resp.status_code == 404:
            raise ConnectorSyncError(f"Remote file '{path}' disappeared during sync")
        if resp.status_code != 200:
            raise ConnectorSyncError(
                f"GitHub could not fetch '{path}' (HTTP {resp.status_code})"
            )
        return resp.content

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
        """Fetch README + docs/**/*.md and index them as deduped Documents."""
        # Lazy imports: heavy worker-only deps + DB access.
        from apps.api.models.document import Document
        from apps.api.models.document_version import DocumentVersion
        from apps.api.db.base import Base
        from apps.worker.chunking import chunk_text
        from apps.worker.embeddings import ensure_collection, generate_embeddings, index_chunks
        from apps.worker.workflow_executor import get_sync_engine
        from ekoa_utils.naming import workspace_collection_name
        from sqlalchemy.orm import Session

        validated = self.test_connection(config, access_token)
        owner, repo = _normalise_config(config)
        branch = validated.get("default_branch", "main")
        repo_label = f"{owner}/{repo}"

        engine = engine or get_sync_engine()
        Base.metadata.create_all(engine, checkfirst=True)

        paths = self._repo_tree_files(config, access_token, branch)
        collection_name = workspace_collection_name(workspace_id)
        result = ConnectorSyncResult()

        with Session(engine) as db:
            for path in paths:
                identity = f"github://{repo_label}/{path}"
                try:
                    content = self._fetch_raw(config, access_token, path)
                    text = content.decode("utf-8", errors="replace")
                    checksum = hashlib.sha256(content).hexdigest()
                except ConnectorSyncError as exc:
                    result.files_failed += 1
                    result.details.append(f"{path}: {exc}")
                    logger.warning("Connector sync file failed %s: %s", identity, exc)
                    continue

                # Re-sync dedup: a Document already indexed from this connector
                # for the exact same file whose latest version checksum matches
                # is skipped — only changed files are reprocessed.
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

                chunks = chunk_text(text)
                try:
                    embeddings = generate_embeddings(chunks) if chunks else []
                    vector_size = len(embeddings[0]) if embeddings else 384
                    ensure_collection(collection_name, vector_size=vector_size)
                except Exception as exc:  # noqa: BLE001
                    db.rollback()
                    raise ConnectorSyncError(
                        f"Embedding/index infrastructure failed for '{path}': "
                        f"{type(exc).__name__}: {exc}"
                    ) from exc

                if doc is None:
                    doc = Document(
                        title=path,
                        content_type="text/markdown",
                        status="PROCESSING",
                        source_url=f"https://github.com/{repo_label}/blob/{branch}/{path}",
                        file_path=identity,
                        workspace_id=workspace_id,
                        uploaded_by=uploaded_by,
                        metadata_json={
                            "connector": self.provider,
                            "connector_id": str(uploaded_by),
                            "repo": repo_label,
                            "path": path,
                            "source": "github",
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
                        f"Failed to index '{path}' into the vector store: "
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
                    f"{path}: indexed {chunk_count} chunks (v{version_number})"
                )

            db.commit()

        result.details.insert(
            0,
            f"repo={repo_label} branch={branch} files={len(paths)} "
            f"created={result.files_created} skipped={result.files_skipped} "
            f"failed={result.files_failed} chunks={result.chunk_count}",
        )
        return result

    def health_check(self, config: dict, access_token: str, connector_status: dict) -> ConnectorHealth:
        """Report real health: is the stored token still valid + last sync state."""
        owner, repo = _normalise_config(config)
        try:
            resp = _github_request(
                "GET",
                f"{GITHUB_API}/repos/{owner}/{repo}",
                access_token,
            )
        except httpx.HTTPError as exc:
            return ConnectorHealth(
                token_valid=False,
                detail=f"GitHub unreachable: {type(exc).__name__}",
                last_sync_status=connector_status.get("last_sync_status"),
                last_sync_error=connector_status.get("last_sync_error"),
                last_sync_at=connector_status.get("last_sync_at"),
            )

        if resp.status_code == 200:
            data = resp.json()
            return ConnectorHealth(
                token_valid=True,
                detail=f"Token valid, repository '{data.get('full_name', f'{owner}/{repo}')}' accessible",
                last_sync_status=connector_status.get("last_sync_status"),
                last_sync_error=connector_status.get("last_sync_error"),
                last_sync_at=connector_status.get("last_sync_at"),
            )
        if resp.status_code in (401, 403):
            return ConnectorHealth(
                token_valid=False,
                detail="Stored token is invalid, expired, or revoked",
                last_sync_status=connector_status.get("last_sync_status"),
                last_sync_error=connector_status.get("last_sync_error"),
                last_sync_at=connector_status.get("last_sync_at"),
            )
        return ConnectorHealth(
            token_valid=False,
            detail=f"Repository check failed (HTTP {resp.status_code})",
            last_sync_status=connector_status.get("last_sync_status"),
            last_sync_error=connector_status.get("last_sync_error"),
            last_sync_at=connector_status.get("last_sync_at"),
        )
