from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.engine import get_db
from apps.api.dependencies.auth import get_current_user
from apps.api.dependencies import authz
from apps.api.models.user import User
from apps.api.services import workspace_service, audit_service
from ekoa_types.workspace import WorkspaceCreate, WorkspaceResponse

router = APIRouter(prefix="/api/v1/workspaces", tags=["Workspaces"])


@router.post("/", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    workspace_data: WorkspaceCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new workspace within an organization."""
    await authz.assert_can_access_org(workspace_data.organization_id, current_user, db)

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
        details={"name": workspace.name, "organization_id": str(workspace.organization_id)}
    )

    return workspace


@router.get("/", response_model=list[WorkspaceResponse])
async def list_workspaces(
    organization_id: uuid.UUID = Query(..., description="Filter workspaces by organization ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve all workspaces belonging to a specific organization."""
    await authz.assert_can_access_org(organization_id, current_user, db)
    return await workspace_service.get_workspaces_by_org(db, organization_id)


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
