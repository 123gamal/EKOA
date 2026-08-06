from __future__ import annotations

import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from apps.api.models.audit_log import AuditLog


async def log_action(
    db: AsyncSession,
    user_id: uuid.UUID | None,
    action: str,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    details: dict | None = None,
    ip_address: str | None = None
) -> AuditLog:
    """Record an audit log entry for system visibility."""
    log = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip_address=ip_address
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return log
