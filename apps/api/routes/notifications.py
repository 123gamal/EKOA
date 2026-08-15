from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select

from apps.api.db.engine import get_db
from apps.api.dependencies.auth import get_current_user
from apps.api.models.notification import Notification
from apps.api.models.user import User
from ekoa_types.notification import NotificationResponse
from ekoa_types.pagination import (
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    Paginated,
)

router = APIRouter(prefix="/api/v1/notifications", tags=["Notifications"])


@router.get("/", response_model=Paginated[NotificationResponse])
async def list_notifications(
    unread_only: bool = Query(False, description="Return only unread notifications"),
    page: int = Query(DEFAULT_PAGE, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Items per page"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the current user's own notifications (never another user's)."""
    base = select(Notification).where(Notification.user_id == current_user.id)
    if unread_only:
        base = base.where(Notification.read_at.is_(None))

    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()

    stmt = (
        base.order_by(Notification.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list((await db.execute(stmt)).scalars().all())
    return Paginated.create(items, total, page, page_size)


@router.get("/unread-count")
async def unread_count(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Unread notification count for the current user (for a nav bell badge)."""
    count = (
        await db.execute(
            select(func.count()).select_from(
                select(Notification)
                .where(Notification.user_id == current_user.id, Notification.read_at.is_(None))
                .subquery()
            )
        )
    ).scalar_one()
    return {"unread_count": count}


@router.post("/{notification_id}/read", response_model=NotificationResponse)
async def mark_read(
    notification_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark one of the current user's own notifications as read."""
    stmt = select(Notification).where(
        Notification.id == notification_id, Notification.user_id == current_user.id
    )
    notification = (await db.execute(stmt)).scalar_one_or_none()
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")

    if notification.read_at is None:
        notification.read_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(notification)
    return notification
