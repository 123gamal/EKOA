from __future__ import annotations

import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from apps.api.models.workspace import Workspace


async def create_workspace(
    db: AsyncSession,
    name: str,
    description: str | None,
    organization_id: uuid.UUID,
    created_by: uuid.UUID
) -> Workspace:
    """Create a new workspace within an organization."""
    workspace = Workspace(
        name=name,
        description=description,
        organization_id=organization_id,
        created_by=created_by
    )
    db.add(workspace)
    await db.commit()
    await db.refresh(workspace)
    return workspace


async def get_workspaces_by_org(db: AsyncSession, organization_id: uuid.UUID) -> list[Workspace]:
    """Retrieve all workspaces belonging to an organization."""
    stmt = select(Workspace).where(Workspace.organization_id == organization_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_workspace_by_id(db: AsyncSession, workspace_id: uuid.UUID) -> Workspace | None:
    """Retrieve a workspace by ID."""
    stmt = select(Workspace).where(Workspace.id == workspace_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
