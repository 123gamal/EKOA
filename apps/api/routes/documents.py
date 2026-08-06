from __future__ import annotations

import uuid
import os
import shutil
import logging
from fastapi import APIRouter, Depends, HTTPException, File, Form, UploadFile, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from apps.api.db.engine import get_db
from apps.api.dependencies.auth import get_current_user
from apps.api.dependencies import authz
from apps.api.models.user import User
from apps.api.models.document import Document
from apps.api.services import audit_service
from ekoa_config.settings import get_settings
from ekoa_types.document import DocumentResponse, DocumentStatus

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

    # Save file contents locally
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not save file: {str(e)}"
        )

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

    db.add(document)
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
        process_document.delay(str(document.id))
    except Exception as e:
        document.status = DocumentStatus.ENQUEUE_FAILED
        await db.commit()
        await db.refresh(document)
        logger.error(
            "Failed to enqueue document %s for processing: %s: %s",
            document.id, type(e).__name__, e,
        )

    return document


@router.get("/", response_model=list[DocumentResponse])
async def list_documents(
    workspace_id: uuid.UUID = Query(..., description="Filter documents by workspace ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve all documents uploaded within a specific workspace."""
    # Verify the current user can access the target workspace
    await authz.assert_can_access_workspace(workspace_id, current_user, db)

    stmt = select(Document).where(Document.workspace_id == workspace_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve metadata details for a specific document by ID."""
    # Verify the current user can access the document (404 if not found in an accessible org)
    await authz.assert_can_access_document(document_id, current_user, db)

    stmt = select(Document).where(Document.id == document_id)
    result = await db.execute(stmt)
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    return document
