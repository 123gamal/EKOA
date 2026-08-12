from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.engine import get_db
from apps.api.dependencies.auth import get_current_user
from apps.api.dependencies import authz
from apps.api.models.audit_log import AuditLog
from apps.api.models.organization import Organization
from apps.api.models.user import User
from ekoa_types.activity import ActivityEntry
from ekoa_types.pagination import DEFAULT_PAGE, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Paginated

router = APIRouter(tags=["Activity"])


@router.get(
    "/api/v1/organizations/{org_id}/activity",
    response_model=Paginated[ActivityEntry],
)
async def list_activity(
    org_id: uuid.UUID,
    page: int = Query(DEFAULT_PAGE, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Team activity feed: recent audited actions in this organization.

    Reads the existing AuditLog table, scoped by ``organization_id`` (added
    in Phase 13 — only entries written since then, from routes that pass it,
    appear here; this is disclosed, not a bug).
    """
    org = (
        await db.execute(
            select(Organization).where(
                Organization.id == org_id, Organization.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    await authz.assert_org_membership(db, current_user.id, org.id)

    base = select(AuditLog, User).outerjoin(User, User.id == AuditLog.user_id).where(
        AuditLog.organization_id == org.id
    )
    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()

    stmt = (
        base.order_by(AuditLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(stmt)).all()
    items = [
        ActivityEntry(
            id=log.id,
            user_id=log.user_id,
            actor_name=user.full_name if user else None,
            actor_email=user.email if user else None,
            action=log.action,
            resource_type=log.resource_type,
            resource_id=log.resource_id,
            details=log.details,
            created_at=log.created_at,
        )
        for log, user in rows
    ]
    return Paginated.create(items, total, page, page_size)
