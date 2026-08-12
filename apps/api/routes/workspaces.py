from __future__ import annotations

import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select

from apps.api.db.engine import get_db
from apps.api.dependencies.auth import get_current_user
from apps.api.dependencies import authz
from apps.api.models.user import User
from apps.api.models.workspace import Workspace
from apps.api.models.workspace_member import WorkspaceMember
from apps.api.models.organization import Organization
from apps.api.services import workspace_service, audit_service
from ekoa_types.workspace import WorkspaceCreate, WorkspaceResponse
from ekoa_types.workspace_member import (
    WorkspaceMemberOverrideRequest,
    WorkspaceMemberOverrideResponse,
)
from ekoa_types.pagination import (
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    Paginated,
)

router = APIRouter(prefix="/api/v1/workspaces", tags=["Workspaces"])


@router.post("/", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    workspace_data: WorkspaceCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new workspace within an organization."""
    await authz.assert_can_access_org(workspace_data.organization_id, current_user, db)
    await authz.assert_min_role(db, current_user.id, workspace_data.organization_id, "admin")

    workspace = await workspace_service.create_workspace(
        db,
        name=workspace_data.name,
        description=workspace_data.description,
        organization_id=workspace_data.organization_id,
        created_by=current_user.id
    )

    await audit_service.log_action(
        db,
        user_id=current_user.id,
        action="workspace.create",
        resource_type="workspaces",
        resource_id=workspace.id,
        details={"name": workspace.name, "organization_id": str(workspace.organization_id)},
        organization_id=workspace.organization_id,
    )

    return workspace


@router.get("/", response_model=Paginated[WorkspaceResponse])
async def list_workspaces(
    organization_id: uuid.UUID = Query(..., description="Filter workspaces by organization ID"),
    page: int = Query(DEFAULT_PAGE, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Items per page"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve workspaces belonging to a specific organization (paginated, latest first)."""
    await authz.assert_can_access_org(organization_id, current_user, db)

    base = (
        select(Workspace)
        .join(Organization, Organization.id == Workspace.organization_id)
        .where(
            Workspace.organization_id == organization_id,
            Workspace.deleted_at.is_(None),
            Organization.deleted_at.is_(None),
        )
    )
    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()

    stmt = (
        base.order_by(Workspace.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list((await db.execute(stmt)).scalars().all())
    return Paginated.create(items, total, page, page_size)


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    workspace_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve details for a specific workspace by ID."""
    await authz.assert_can_access_workspace(workspace_id, current_user, db)

    workspace = await workspace_service.get_workspace_by_id(db, workspace_id)
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found"
        )
    return workspace


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    workspace_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Soft-delete a workspace (admin role or higher, in this workspace specifically). The row is kept with deleted_at set."""
    workspace = await workspace_service.get_workspace_by_id(db, workspace_id)
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found"
        )

    await authz.assert_can_access_org(workspace.organization_id, current_user, db)
    # Phase 13: consults a per-workspace role override if one exists for this
    # user (falls back to their org role otherwise, so this is unchanged
    # behavior for every workspace without an explicit override).
    await authz.assert_workspace_min_role(
        db, current_user.id, workspace.id, workspace.organization_id, "admin"
    )

    workspace.deleted_at = datetime.now(timezone.utc)
    db.add(workspace)
    await db.commit()

    await audit_service.log_action(
        db,
        user_id=current_user.id,
        action="workspace.delete",
        resource_type="workspaces",
        resource_id=workspace.id,
        details={"name": workspace.name, "organization_id": str(workspace.organization_id)},
        organization_id=workspace.organization_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Workspace-level role overrides (Phase 13, additive/opt-in) ─────────────


@router.put(
    "/{workspace_id}/members/{user_id}",
    response_model=WorkspaceMemberOverrideResponse,
)
async def set_workspace_member_role(
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    data: WorkspaceMemberOverrideRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set a user's role *within this workspace specifically*. Org admin/owner-only.

    Does not change the user's org-level role; it only overrides what
    ``get_workspace_role`` returns for this one workspace. The target user
    must already be an org member.
    """
    workspace = await workspace_service.get_workspace_by_id(db, workspace_id)
    if not workspace:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    await authz.assert_can_access_org(workspace.organization_id, current_user, db)
    await authz.assert_min_role(db, current_user.id, workspace.organization_id, "admin")

    target_role = await authz.get_org_role(db, user_id, workspace.organization_id)
    if target_role is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Target user is not a member of this organization",
        )

    stmt = select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id
    )
    override = (await db.execute(stmt)).scalar_one_or_none()
    if override is None:
        override = WorkspaceMember(workspace_id=workspace_id, user_id=user_id, role=data.role)
        db.add(override)
    else:
        override.role = data.role
    await db.commit()
    await db.refresh(override)

    await audit_service.log_action(
        db,
        user_id=current_user.id,
        action="workspace_member.set_role",
        resource_type="workspace_members",
        resource_id=override.id,
        details={"workspace_id": str(workspace_id), "target_user_id": str(user_id), "role": data.role},
        organization_id=workspace.organization_id,
    )
    return override


@router.delete(
    "/{workspace_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def clear_workspace_member_role(
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Clear a workspace-level role override; the user reverts to their org role."""
    workspace = await workspace_service.get_workspace_by_id(db, workspace_id)
    if not workspace:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    await authz.assert_can_access_org(workspace.organization_id, current_user, db)
    await authz.assert_min_role(db, current_user.id, workspace.organization_id, "admin")

    stmt = select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id
    )
    override = (await db.execute(stmt)).scalar_one_or_none()
    if override is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    await db.delete(override)
    await db.commit()

    await audit_service.log_action(
        db,
        user_id=current_user.id,
        action="workspace_member.clear_role",
        resource_type="workspace_members",
        resource_id=None,
        details={"workspace_id": str(workspace_id), "target_user_id": str(user_id)},
        organization_id=workspace.organization_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
