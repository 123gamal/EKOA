"""Celery task definitions for document processing pipeline."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

from ekoa_config.settings import get_settings

from apps.api.models.document import Document
from apps.api.db.base import Base
from apps.api.services.connectors.base import (
    ConnectorSyncError,
    ConnectorValidationError,
    get_connector_adapter,
)

from apps.worker.chunking import chunk_text
from apps.worker.main import app
from apps.worker.parsers import parse_file
from apps.worker.workflow_executor import get_sync_engine
from ekoa_config.logging import get_logger, correlation_id_var
from ekoa_config.metrics import CONNECTOR_SYNC_COUNT
from ekoa_utils.naming import workspace_collection_name

logger = logging.getLogger(__name__)

settings = get_settings()


def _apply_correlation(correlation_id: str | None) -> None:
    """Restore the originating request's correlation ID in the task context."""
    if correlation_id:
        correlation_id_var.set(correlation_id)


class RetryableProcessingError(Exception):
    """Transient infrastructure failure (DB/Qdrant/embedding) - safe to retry."""


def process_document_sync(document_id: str) -> None:
    """Synchronous standalone document processing pipeline (for direct execution when Celery is offline).

    Exception contract for the Celery retry path:
    - RetryableProcessingError is re-raised so the task's ``self.retry`` fires on
      transient infrastructure failures (Qdrant down, embedding model unloaded,
      network timeouts).
    - Any other failure (unreadable/unsupported source file, missing file on disk,
      bad document id) is a permanent error: the document is marked FAILED and the
      task must NOT retry.
    """
    from apps.worker.embeddings import ensure_collection, generate_embeddings, index_chunks
    from apps.api.models.workspace import Workspace

    doc_uuid = uuid.UUID(document_id)
    engine = get_sync_engine()
    Base.metadata.create_all(engine, checkfirst=True)

    with Session(engine) as db:
        doc = db.query(Document).filter(Document.id == doc_uuid).first()
        if not doc:
            logger.warning("Document %s not found; skipping", document_id)
            return

        workspace = db.query(Workspace).filter(Workspace.id == doc.workspace_id).first()
        organization_id = workspace.organization_id if workspace else None

        collection_name = workspace_collection_name(doc.workspace_id)

        doc.status = "PROCESSING"
        db.commit()

        # Permanent errors (source file problems) fail fast without retry.
        try:
            text = parse_file(doc.file_path, doc.content_type)
            chunks = chunk_text(text)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            doc.status = "FAILED"
            db.commit()
            logger.error(
                "Document %s permanently failed at parse: %s: %s",
                document_id, type(exc).__name__, exc,
            )
            return

        # Transient errors (embedding/Qdrant infra) re-raise for Celery retry.
        try:
            embeddings = generate_embeddings(chunks) if chunks else []
            vector_size = len(embeddings[0]) if embeddings else 384
            ensure_collection(collection_name, vector_size=vector_size)
            chunk_count = index_chunks(
                collection_name,
                doc.id,
                chunks,
                embeddings,
                organization_id=organization_id,
                workspace_id=doc.workspace_id,
            ) if chunks else 0
        except RetryableProcessingError:
            raise
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            doc.status = "FAILED"
            db.commit()
            logger.error(
                "Document %s transient infra failure (retry scheduled): %s: %s",
                document_id, type(exc).__name__, exc,
            )
            raise RetryableProcessingError(f"{type(exc).__name__}: {exc}") from exc

        doc.status = "INDEXED"
        doc.chunk_count = chunk_count
        db.commit()


@app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_document(self, document_id: str, correlation_id: str | None = None):
    """Parse, chunk, embed, and index a document into Qdrant."""
    _apply_correlation(correlation_id)
    task_logger = get_logger("worker.tasks.process_document")
    task_logger.info("task_started", extra={"task": "process_document", "document_id": document_id})
    try:
        process_document_sync(document_id)
        task_logger.info("task_succeeded", extra={"task": "process_document", "document_id": document_id})
    except RetryableProcessingError as exc:
        logger.warning("Retrying document %s (%s/%s)", document_id, self.request.retries, self.max_retries)
        raise self.retry(exc=exc)
    except Exception as exc:  # noqa: BLE001 - unexpected failure still retried
        logger.exception("Unexpected error processing document %s", document_id)
        raise self.retry(exc=exc)


@app.task(bind=True, max_retries=2, default_retry_delay=30)
def run_workflow(self, run_id: str, correlation_id: str | None = None):
    """Execute a workflow run against the real pipeline."""
    _apply_correlation(correlation_id)
    task_logger = get_logger("worker.tasks.run_workflow")
    task_logger.info("task_started", extra={"task": "run_workflow", "run_id": run_id})
    from apps.worker.workflow_executor import run_workflow_sync

    try:
        run_workflow_sync(run_id)
        task_logger.info("task_succeeded", extra={"task": "run_workflow", "run_id": run_id})
    except Exception as exc:
        raise self.retry(exc=exc)


def _ensure_fresh_credential(db: Session, connector, credential) -> str:
    """Return a usable plaintext access token, refreshing it first if the
    stored one is OAuth2 and expired (Google Drive today; a no-op for every
    other provider since they never populate ``refresh_token_encrypted``)."""
    from ekoa_config.connector_crypto import decrypt_secret, encrypt_secret
    from apps.api.services.connectors.google_drive import token_expired

    token = decrypt_secret(credential.access_token_encrypted)
    if not credential.refresh_token_encrypted:
        return token
    if not token_expired(credential.token_expires_at):
        return token

    adapter = get_connector_adapter(connector.provider)
    refresh_token = decrypt_secret(credential.refresh_token_encrypted)
    refreshed = adapter.refresh_access_token(refresh_token)
    credential.access_token_encrypted = encrypt_secret(refreshed.access_token)
    if refreshed.expires_in:
        credential.token_expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=refreshed.expires_in
        )
    db.commit()
    return refreshed.access_token


def _notify_connector_sync_failed(db: Session, connector, error: str) -> None:
    """Best-effort notification to whoever connected the integration that
    its sync permanently failed. Never raises."""
    try:
        from apps.api.models.user import User
        from apps.api.services import notification_service

        user = db.query(User).filter(User.id == connector.connected_by).first()
        if user is None:
            return
        notification_service.notify_sync(
            db,
            user_id=user.id,
            organization_id=connector.organization_id,
            type="connector.sync_failed",
            title=f"{connector.provider} connector sync failed",
            body=f"'{connector.name}' failed to sync: {error}",
            resource_type="connectors",
            resource_id=connector.id,
            email_to=user.email,
        )
    except Exception:  # noqa: BLE001
        logger.warning("connector_failure_notification_failed", extra={"connector_id": str(connector.id)})


@app.task(bind=True, max_retries=3, default_retry_delay=60)
def sync_connector_task(self, connector_id: str, correlation_id: str | None = None):
    """Sync any connected integration into Qdrant, dispatched by provider.

    The worker holds the decryption key, so the token is only in plaintext
    within this process for the duration of the run. On a permanent failure
    (bad/revoked token, unreachable resource) the connector is marked
    ``error`` with a reason and the task does NOT retry. Transient
    infrastructure failures (DB/Qdrant) retry via
    :class:`RetryableProcessingError`.
    """
    _apply_correlation(correlation_id)
    task_logger = get_logger("worker.tasks.sync_connector_task")
    task_logger.info(
        "task_started", extra={"task": "sync_connector_task", "connector_id": connector_id}
    )
    from apps.api.models.connector import Connector, ConnectorCredential

    connector_uuid = uuid.UUID(connector_id)
    engine = get_sync_engine()
    Base.metadata.create_all(engine, checkfirst=True)

    try:
        with Session(engine) as db:
            connector = db.query(Connector).filter(Connector.id == connector_uuid).first()
            if connector is None or connector.deleted_at is not None:
                task_logger.warning(
                    "connector_not_found", extra={"connector_id": connector_id}
                )
                return

            credential = (
                db.query(ConnectorCredential)
                .filter(ConnectorCredential.connector_id == connector_uuid)
                .first()
            )
            if credential is None:
                connector.status = "error"
                connector.status_reason = "No stored credential to sync with"
                connector.last_sync_status = "failed"
                connector.last_sync_error = "No stored credential to sync with"
                db.commit()
                task_logger.error(
                    "connector_missing_credential", extra={"connector_id": connector_id}
                )
                return

            token = _ensure_fresh_credential(db, connector, credential)
            result = get_connector_adapter(connector.provider).sync(
                connector.config_json or {},
                token,
                workspace_id=connector.workspace_id,
                organization_id=connector.organization_id,
                uploaded_by=connector.connected_by,
                engine=engine,
            )
            connector.status = "connected"
            connector.status_reason = None
            connector.last_sync_at = datetime.now(timezone.utc)
            connector.last_sync_status = "success"
            connector.last_sync_error = None
            connector.last_sync_document_count = result.files_processed
            db.commit()
            CONNECTOR_SYNC_COUNT.labels(provider=connector.provider, status="success").inc()

            task_logger.info(
                "task_succeeded",
                extra={
                    "task": "sync_connector_task",
                    "connector_id": connector_id,
                    "provider": connector.provider,
                    "summary": result.details,
                },
            )
    except (ConnectorValidationError, ConnectorSyncError) as exc:
        # Permanent failure: token invalid/revoked, resource gone. Mark the
        # connector error so the UI/health surface the broken state; no retry.
        with Session(engine) as db:
            connector = db.query(Connector).filter(Connector.id == connector_uuid).first()
            if connector is not None:
                connector.status = "error"
                connector.status_reason = str(exc)
                connector.last_sync_status = "failed"
                connector.last_sync_error = str(exc)
                connector.last_sync_at = datetime.now(timezone.utc)
                db.commit()
                _notify_connector_sync_failed(db, connector, str(exc))
                CONNECTOR_SYNC_COUNT.labels(provider=connector.provider, status="failed").inc()
        task_logger.error(
            "connector_sync_permanent_failure",
            extra={"connector_id": connector_id, "error": str(exc)},
        )
    except RetryableProcessingError as exc:
        with Session(engine) as db:
            connector = db.query(Connector).filter(Connector.id == connector_uuid).first()
            if connector is not None:
                connector.last_sync_status = "failed"
                connector.last_sync_error = "transient infrastructure failure; retry scheduled"
                db.commit()
        logger.warning(
            "Retrying connector sync %s (%s/%s)",
            connector_id, self.request.retries, self.max_retries,
        )
        raise self.retry(exc=exc)
    except Exception as exc:  # noqa: BLE001 - unexpected failure still retried
        with Session(engine) as db:
            connector = db.query(Connector).filter(Connector.id == connector_uuid).first()
            if connector is not None:
                connector.last_sync_status = "failed"
                connector.last_sync_error = f"{type(exc).__name__}: {exc}"
                db.commit()
        logger.exception("Unexpected error syncing connector %s", connector_id)
        raise self.retry(exc=exc)

