"""Authorization helpers: verify a user can access organizations, workspaces, and documents."""

from __future__ import annotations

import uuid
from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from apps.api.db.engine import get_db
from apps.api.dependencies.auth import get_current_user
from apps.api.models.user import User
from apps.api.models.org_member import OrgMember
from apps.api.models.workspace import Workspace
from apps.api.models.document import Document

# Sentinel used so these helpers can be composed via Depends() without a trailing
# DB dependency in every route. FastAPI resolves the inner Depends() calls.
ORG_ACCESS_DEP: Depends = Depends(get_current_user)


async def _org_id_for_workspace(db: AsyncSession, workspace_id: uuid.UUID) -> uuid.UUID | None:
    stmt = select(Workspace.organization_id).where(Workspace.id == workspace_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _org_id_for_document(db: AsyncSession, document_id: uuid.UUID) -> uuid.UUID | None:
    stmt = (
        select(Workspace.organization_id)
        .join(Document, Document.workspace_id == Workspace.id)
        .where(Document.id == document_id)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def assert_org_membership(
    db: AsyncSession, user_id: uuid.UUID, org_id: uuid.UUID
) -> None:
    """Raise 403 if the user is not an active member of the organization."""
    stmt = select(OrgMember).where(
        OrgMember.organization_id == org_id,
        OrgMember.user_id == user_id,
    )
    result = await db.execute(stmt)
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this organization",
        )


async def assert_can_access_org(
    org_id: uuid.UUID,
    current_user: User = Depends(ORG_ACCESS_DEP),
    db: AsyncSession = Depends(get_db),
) -> None:
    await assert_org_membership(db, current_user.id, org_id)


async def assert_can_access_workspace(
    workspace_id: uuid.UUID,
    current_user: User = Depends(ORG_ACCESS_DEP),
    db: AsyncSession = Depends(get_db),
) -> None:
    org_id = await _org_id_for_workspace(db, workspace_id)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    await assert_org_membership(db, current_user.id, org_id)


async def assert_can_access_document(
    document_id: uuid.UUID,
    current_user: User = Depends(ORG_ACCESS_DEP),
    db: AsyncSession = Depends(get_db),
) -> None:
    org_id = await _org_id_for_document(db, document_id)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    await assert_org_membership(db, current_user.id, org_id)