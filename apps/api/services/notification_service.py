"""Create in-app notifications, optionally mirrored to email.

Two entry points because the two real trigger points wired in Phase 16 run
in different DB contexts: ``notify`` for async callers (API/AI routes),
``notify_sync`` for the worker's synchronous Celery tasks (workflow
approval-pause, connector sync permanent failure). Both just insert a
``Notification`` row; email is best-effort and never blocks the caller's
primary flow (a failed email must not fail a workflow pause or a connector
sync).
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from apps.api.models.notification import Notification
from ekoa_config.logging import get_logger

logger = get_logger("api.services.notification")


def _build(
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID | None,
    type: str,
    title: str,
    body: str | None,
    resource_type: str | None,
    resource_id: uuid.UUID | None,
) -> Notification:
    return Notification(
        user_id=user_id,
        organization_id=organization_id,
        type=type,
        title=title,
        body=body,
        resource_type=resource_type,
        resource_id=resource_id,
    )


async def notify(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID | None,
    type: str,
    title: str,
    body: str | None = None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    email_to: str | None = None,
) -> Notification:
    """Create a notification from an async (API/AI service) context."""
    notification = _build(
        user_id=user_id, organization_id=organization_id, type=type, title=title,
        body=body, resource_type=resource_type, resource_id=resource_id,
    )
    db.add(notification)
    await db.commit()
    await db.refresh(notification)

    if email_to:
        from apps.api.services.email_service import send_email
        try:
            await send_email(email_to, title, f"<p>{body or title}</p>")
        except Exception:  # noqa: BLE001
            logger.warning("notification_email_failed", extra={"type": type, "to": email_to})

    return notification


def notify_sync(
    db: Session,
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID | None,
    type: str,
    title: str,
    body: str | None = None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    email_to: str | None = None,
) -> Notification:
    """Create a notification from a sync (worker) context."""
    notification = _build(
        user_id=user_id, organization_id=organization_id, type=type, title=title,
        body=body, resource_type=resource_type, resource_id=resource_id,
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)

    if email_to:
        from apps.api.services.email_service import _send_sync
        try:
            _send_sync(email_to, title, f"<p>{body or title}</p>")
        except Exception:  # noqa: BLE001
            logger.warning("notification_email_failed", extra={"type": type, "to": email_to})

    return notification
