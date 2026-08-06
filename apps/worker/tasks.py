"""Celery task definitions for document processing pipeline."""

from __future__ import annotations

import logging
import uuid
from sqlalchemy.orm import Session

from ekoa_config.settings import get_settings

from apps.api.models.document import Document
from apps.api.db.base import Base

from apps.worker.chunking import chunk_text
from apps.worker.main import app
from apps.worker.parsers import parse_file
from apps.worker.workflow_executor import get_sync_engine
from ekoa_config.logging import get_logger, correlation_id_var
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

    doc_uuid = uuid.UUID(document_id)
    engine = get_sync_engine()
    Base.metadata.create_all(engine, checkfirst=True)

    with Session(engine) as db:
        doc = db.query(Document).filter(Document.id == doc_uuid).first()
        if not doc:
            logger.warning("Document %s not found; skipping", document_id)
            return

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
            chunk_count = index_chunks(collection_name, doc.id, chunks, embeddings) if chunks else 0
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

