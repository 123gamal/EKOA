from __future__ import annotations

import uuid
import os
import hashlib
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, File, Form, UploadFile, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select

from apps.api.db.engine import get_db
from apps.api.dependencies.auth import get_current_user
from apps.api.dependencies import authz
from apps.api.models.user import User
from apps.api.models.document import Document
from apps.api.models.document_version import DocumentVersion
from apps.api.services import audit_service
from ekoa_config.settings import get_settings
from ekoa_config.logging import get_correlation_id
from ekoa_types.document import DocumentResponse, DocumentStatus
from ekoa_types.pagination import (
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    Paginated,
)

router = APIRouter(prefix="/api/v1/documents", tags=["Documents"])

logger = logging.getLogger(__name__)

settings = get_settings()

# Local uploads folder path
UPLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "uploads"))


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    workspace_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Upload a file to a specific workspace. The file metadata is indexed as PENDING."""
    # Verify the current user can access the target workspace
    await authz.assert_can_access_workspace(workspace_id, current_user, db)

    # Ensure upload directory exists
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    # Generate unique filename to prevent collisions
    file_id = uuid.uuid4()
    extension = os.path.splitext(file.filename)[1] if file.filename else ""
    local_filename = f"{file_id}{extension}"
    file_path = os.path.join(UPLOAD_DIR, local_filename)

    # Save file contents locally, computing the sha256 checksum while streaming
    # so we never hold the whole file in memory and never read it twice.
    file_sha256 = hashlib.sha256()
    try:
        with open(file_path, "wb") as buffer:
            while chunk := file.file.read(1024 * 1024):
                buffer.write(chunk)
                file_sha256.update(chunk)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not save file: {str(e)}"
        )
    checksum = file_sha256.hexdigest()

    # Create Document metadata in DB
    document = Document(
        id=file_id,
        title=file.filename or "Untitled",
        content_type=file.content_type or "application/octet-stream",
        status=DocumentStatus.PENDING,
        file_path=file_path,
        workspace_id=workspace_id,
        uploaded_by=current_user.id
    )

    # Record version 1 of this document. Language detection of the uploaded
    # file is intentionally not performed here: no language-detection library
    # (langdetect/langid/py3langid) exists in the dependency stack, and adding
    # one would require a new dependency (blocked while the image registry is
    # unreachable). Re-upload to a new version (N+1) is a future phase.
    document_version = DocumentVersion(
        document_id=document.id,
        version=1,
        file_path=file_path,
        checksum=checksum,
        status=DocumentStatus.PENDING,
        uploaded_by=current_user.id
    )

    db.add(document)
    db.add(document_version)
    await db.commit()
    await db.refresh(document)

    await audit_service.log_action(
        db,
        user_id=current_user.id,
        action="document.upload",
        resource_type="documents",
        resource_id=document.id,
        details={"title": document.title, "workspace_id": str(workspace_id)}
    )

    # Enqueue background processing to the Celery worker (which has the
    # document-processing dependencies: torch, qdrant-client, embeddings).
    # A failed enqueue must be visible: mark the document and log instead of
    # silently swallowing the error.
    try:
        from apps.worker.tasks import process_document
        process_document.delay(str(document.id), correlation_id=get_correlation_id())
    except Exception as e:
        document.status = DocumentStatus.ENQUEUE_FAILED
        await db.commit()
        await db.refresh(document)
        logger.error(
            "Failed to enqueue document %s for processing: %s: %s",
            document.id, type(e).__name__, e,
        )

    return document


@router.get("/", response_model=Paginated[DocumentResponse])
async def list_documents(
    workspace_id: uuid.UUID = Query(..., description="Filter documents by workspace ID"),
    page: int = Query(DEFAULT_PAGE, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Items per page"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve documents uploaded within a specific workspace (paginated, latest first)."""
    # Verify the current user can access the target workspace
    await authz.assert_can_access_workspace(workspace_id, current_user, db)

    base = select(Document).where(
        Document.workspace_id == workspace_id,
        Document.deleted_at.is_(None),
    )
    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()

    stmt = (
        base.order_by(Document.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list((await db.execute(stmt)).scalars().all())
    return Paginated.create(items, total, page, page_size)


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve metadata details for a specific document by ID."""
    # Verify the current user can access the document (404 if not found in an accessible org)
    await authz.assert_can_access_document(document_id, current_user, db)

    stmt = select(Document).where(
        Document.id == document_id,
        Document.deleted_at.is_(None),
    )
    result = await db.execute(stmt)
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    return document


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Soft-delete a document. The row is kept with deleted_at set."""
    await authz.assert_can_access_document(document_id, current_user, db)

    stmt = select(Document).where(
        Document.id == document_id,
        Document.deleted_at.is_(None),
    )
    result = await db.execute(stmt)
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )

    document.deleted_at = datetime.now(timezone.utc)
    db.add(document)
    await db.commit()

    await audit_service.log_action(
        db,
        user_id=current_user.id,
        action="document.delete",
        resource_type="documents",
        resource_id=document.id,
        details={"title": document.title, "workspace_id": str(document.workspace_id)}
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{document_id}/versions")
async def list_document_versions(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List all persisted versions of a document (oldest first)."""
    await authz.assert_can_access_document(document_id, current_user, db)

    stmt = (
        select(DocumentVersion)
        .where(DocumentVersion.document_id == document_id)
        .order_by(DocumentVersion.version.asc())
    )
    result = await db.execute(stmt)
    versions = result.scalars().all()

    return {
        "document_id": str(document_id),
        "items": [
            {
                "id": str(v.id),
                "version": v.version,
                "checksum": v.checksum,
                "status": v.status,
                "uploaded_by": str(v.uploaded_by),
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
            for v in versions
        ],
    }
