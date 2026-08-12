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
from apps.api.models.organization import Organization
from apps.api.models.workspace import Workspace
from apps.api.models.workspace_member import WorkspaceMember
from apps.api.models.document import Document

# Sentinel used so these helpers can be composed via Depends() without a trailing
# DB dependency in every route. FastAPI resolves the inner Depends() calls.
ORG_ACCESS_DEP: Depends = Depends(get_current_user)

# Role hierarchy already present in the data model (org_members.role column).
# No new roles introduced; higher level = more privileged.
ROLE_LEVELS: dict[str, int] = {
    "owner": 3,
    "admin": 2,
    "member": 1,
}


async def _org_id_for_workspace(db: AsyncSession, workspace_id: uuid.UUID) -> uuid.UUID | None:
    # A soft-deleted workspace is treated as non-existent.
    stmt = select(Workspace.organization_id).where(
        Workspace.id == workspace_id,
        Workspace.deleted_at.is_(None),
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _org_id_for_document(db: AsyncSession, document_id: uuid.UUID) -> uuid.UUID | None:
    # Soft-deleted documents and workspaces resolve to no org → callers get 404.
    stmt = (
        select(Workspace.organization_id)
        .join(Document, Document.workspace_id == Workspace.id)
        .where(
            Document.id == document_id,
            Document.deleted_at.is_(None),
            Workspace.deleted_at.is_(None),
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def org_id_for_workspace(db: AsyncSession, workspace_id: uuid.UUID) -> uuid.UUID | None:
    """Public helper: resolve the organization that owns a workspace."""
    return await _org_id_for_workspace(db, workspace_id)


async def get_org_role(db: AsyncSession, user_id: uuid.UUID, org_id: uuid.UUID) -> str | None:
    """Return the caller's role in an organization (or None if not a member)."""
    stmt = select(OrgMember.role).where(
        OrgMember.organization_id == org_id,
        OrgMember.user_id == user_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def assert_min_role(
    db: AsyncSession,
    user_id: uuid.UUID,
    org_id: uuid.UUID,
    min_role: str,
) -> None:
    """Raise 403 unless the caller's role in the org meets ``min_role``.

    Hierarchy (owner > admin > member) is defined in :data:`ROLE_LEVELS`.
    This is a foundational RBAC check on top of plain membership: it must be
    composed with an existing ``assert_org_membership`` (or the equivalent
    ``assert_can_access_*``) check, and is exercised meaningfully once the
    invite flow (FR-202) exists to create non-owner members.
    """
    if min_role not in ROLE_LEVELS:
        raise ValueError(f"Unknown role: {min_role!r}")

    role = await get_org_role(db, user_id, org_id)
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this organization",
        )
    if ROLE_LEVELS.get(role, 0) < ROLE_LEVELS[min_role]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action",
        )


async def assert_org_membership(
    db: AsyncSession, user_id: uuid.UUID, org_id: uuid.UUID
) -> None:
    """Raise 403 if the user is not an active member of a non-deleted organization."""
    stmt = (
        select(OrgMember)
        .join(Organization, Organization.id == OrgMember.organization_id)
        .where(
            OrgMember.organization_id == org_id,
            OrgMember.user_id == user_id,
            Organization.deleted_at.is_(None),
        )
    )
    result = await db.execute(stmt)
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this organization",
        )


async def get_workspace_role(
    db: AsyncSession, user_id: uuid.UUID, workspace_id: uuid.UUID, org_id: uuid.UUID
) -> str | None:
    """Return the caller's effective role *within this workspace* (Phase 13).

    Additive on top of org-level membership: if a :class:`WorkspaceMember`
    row exists for this (user, workspace) it wins (an explicit per-workspace
    override, e.g. workspace-admin without org-admin); otherwise this falls
    back to the user's org role, so a workspace with no overrides behaves
    exactly as it did before this existed. Most routes still use
    ``get_org_role``/``assert_min_role`` directly and never consult this —
    see ``workspaces.py``'s delete route for the one place it's enforced so
    far.
    """
    stmt = select(WorkspaceMember.role).where(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.user_id == user_id,
    )
    override = (await db.execute(stmt)).scalar_one_or_none()
    if override is not None:
        return override
    return await get_org_role(db, user_id, org_id)


async def assert_workspace_min_role(
    db: AsyncSession,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    org_id: uuid.UUID,
    min_role: str,
) -> None:
    """Raise 403 unless the caller's effective workspace role meets ``min_role``."""
    if min_role not in ROLE_LEVELS:
        raise ValueError(f"Unknown role: {min_role!r}")

    role = await get_workspace_role(db, user_id, workspace_id, org_id)
    if role is None or ROLE_LEVELS.get(role, 0) < ROLE_LEVELS[min_role]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action",
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