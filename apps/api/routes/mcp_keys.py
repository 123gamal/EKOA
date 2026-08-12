from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select

from apps.api.db.engine import get_db
from apps.api.dependencies.auth import get_current_user
from apps.api.dependencies import authz
from apps.api.models.user import User
from apps.api.models.mcp_api_key import McpApiKey
from apps.api.services import audit_service
from ekoa_config.logging import get_logger
from ekoa_types.mcp import (
    KEY_PREFIX,
    McpApiKeyCreateRequest,
    McpApiKeyCreatedResponse,
    McpApiKeyResponse,
    McpApiKeyStatus,
    generate_mcp_api_key,
)
from ekoa_types.pagination import (
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    Paginated,
)

router = APIRouter(prefix="/api/v1/mcp/keys", tags=["MCP API Keys"])

logger = get_logger("api.routes.mcp_keys")


def _hash_key(raw_key: str) -> str:
    """SHA-256 hex digest of a raw MCP API key (the only thing persisted)."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


async def _load_active_key(db: AsyncSession, key_id: uuid.UUID) -> McpApiKey | None:
    stmt = select(McpApiKey).where(McpApiKey.id == key_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


@router.post("/", response_model=McpApiKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_mcp_api_key(
    data: McpApiKeyCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a workspace-scoped MCP API key. Admin/owner-only and audited.

    The raw key is returned exactly once in the response; only its SHA-256
    hash and an identifying prefix are persisted.
    """
    await authz.assert_can_access_workspace(data.workspace_id, current_user, db)
    org_id = await authz.org_id_for_workspace(db, data.workspace_id)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found"
        )
    await authz.assert_min_role(db, current_user.id, org_id, "admin")

    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=data.expires_in_days)
        if data.expires_in_days is not None
        else None
    )
    raw_key = generate_mcp_api_key(org_id, data.workspace_id)
    api_key = McpApiKey(
        organization_id=org_id,
        workspace_id=data.workspace_id,
        name=data.name,
        key_hash=_hash_key(raw_key),
        key_prefix=f"{KEY_PREFIX}{str(org_id)[:8]}_{str(data.workspace_id)[:8]}",
        status=McpApiKeyStatus.ACTIVE.value,
        created_by=current_user.id,
        expires_at=expires_at,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    await audit_service.log_action(
        db,
        user_id=current_user.id,
        action="mcp_api_key.create",
        resource_type="mcp_api_keys",
        resource_id=api_key.id,
        details={
            "name": api_key.name,
            "workspace_id": str(api_key.workspace_id),
            "organization_id": str(api_key.organization_id),
            "key_prefix": api_key.key_prefix,
            "expires_at": api_key.expires_at.isoformat() if api_key.expires_at else None,
        },
        organization_id=org_id,
    )
    logger.info(
        "mcp_api_key_created",
        extra={
            "key_id": str(api_key.id),
            "workspace_id": str(api_key.workspace_id),
            "organization_id": str(api_key.organization_id),
            "user_id": str(current_user.id),
        },
    )
    return McpApiKeyCreatedResponse(
        id=api_key.id,
        organization_id=api_key.organization_id,
        workspace_id=api_key.workspace_id,
        name=api_key.name,
        key=raw_key,
        key_prefix=api_key.key_prefix,
        status=McpApiKeyStatus(api_key.status),
        created_by=api_key.created_by,
        created_at=api_key.created_at,
        expires_at=api_key.expires_at,
    )


@router.get("/", response_model=Paginated[McpApiKeyResponse])
async def list_mcp_api_keys(
    workspace_id: uuid.UUID = Query(...),
    page: int = Query(DEFAULT_PAGE, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List MCP API keys in a workspace (paginated, latest first). Admin-gated.

    Returns metadata only (prefix + lifecycle) — never the plaintext key.
    """
    await authz.assert_can_access_workspace(workspace_id, current_user, db)
    org_id = await authz.org_id_for_workspace(db, workspace_id)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found"
        )
    await authz.assert_min_role(db, current_user.id, org_id, "admin")

    base = select(McpApiKey).where(McpApiKey.workspace_id == workspace_id)
    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()

    stmt = (
        base.order_by(McpApiKey.created_at.desc(), McpApiKey.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list((await db.execute(stmt)).scalars().all())
    return Paginated.create(items, total, page, page_size)


@router.post("/{key_id}/revoke", response_model=McpApiKeyResponse)
async def revoke_mcp_api_key(
    key_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke an MCP API key. Admin/owner-only and audited.

    A revoked key is rejected by the MCP server immediately on its next use.
    """
    api_key = await _load_active_key(db, key_id)
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="MCP API key not found"
        )
    await authz.assert_can_access_workspace(api_key.workspace_id, current_user, db)
    org_id = await authz.org_id_for_workspace(db, api_key.workspace_id)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found"
        )
    await authz.assert_min_role(db, current_user.id, org_id, "admin")

    if api_key.status == McpApiKeyStatus.REVOKED.value:
        await db.refresh(api_key)
        return api_key

    api_key.status = McpApiKeyStatus.REVOKED.value
    api_key.revoked_at = datetime.now(timezone.utc)
    api_key.revoked_by = current_user.id
    await db.commit()
    await db.refresh(api_key)

    await audit_service.log_action(
        db,
        user_id=current_user.id,
        action="mcp_api_key.revoke",
        resource_type="mcp_api_keys",
        resource_id=api_key.id,
        details={
            "name": api_key.name,
            "workspace_id": str(api_key.workspace_id),
            "organization_id": str(api_key.organization_id),
            "key_prefix": api_key.key_prefix,
        },
        organization_id=org_id,
    )
    logger.info(
        "mcp_api_key_revoked",
        extra={
            "key_id": str(api_key.id),
            "workspace_id": str(api_key.workspace_id),
            "user_id": str(current_user.id),
        },
    )
    return api_key


@router.post("/{key_id}/rotate", response_model=McpApiKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
async def rotate_mcp_api_key(
    key_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rotate an MCP API key: issue a replacement, then revoke the old one.

    Admin/owner-only and audited, same as create/revoke. The new key's raw
    value is returned exactly once, same as at creation; the old key stops
    working on its next use, same as an explicit revoke.
    """
    old_key = await _load_active_key(db, key_id)
    if old_key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="MCP API key not found"
        )
    await authz.assert_can_access_workspace(old_key.workspace_id, current_user, db)
    org_id = await authz.org_id_for_workspace(db, old_key.workspace_id)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found"
        )
    await authz.assert_min_role(db, current_user.id, org_id, "admin")

    raw_key = generate_mcp_api_key(org_id, old_key.workspace_id)
    new_key = McpApiKey(
        organization_id=org_id,
        workspace_id=old_key.workspace_id,
        name=f"{old_key.name} (rotated)",
        key_hash=_hash_key(raw_key),
        key_prefix=f"{KEY_PREFIX}{str(org_id)[:8]}_{str(old_key.workspace_id)[:8]}",
        status=McpApiKeyStatus.ACTIVE.value,
        created_by=current_user.id,
        expires_at=old_key.expires_at,
    )
    db.add(new_key)

    if old_key.status != McpApiKeyStatus.REVOKED.value:
        old_key.status = McpApiKeyStatus.REVOKED.value
        old_key.revoked_at = datetime.now(timezone.utc)
        old_key.revoked_by = current_user.id

    await db.commit()
    await db.refresh(new_key)

    await audit_service.log_action(
        db,
        user_id=current_user.id,
        action="mcp_api_key.rotate",
        resource_type="mcp_api_keys",
        resource_id=new_key.id,
        details={
            "old_key_id": str(old_key.id),
            "new_key_id": str(new_key.id),
            "workspace_id": str(new_key.workspace_id),
            "organization_id": str(new_key.organization_id),
            "key_prefix": new_key.key_prefix,
        },
        organization_id=org_id,
    )
    logger.info(
        "mcp_api_key_rotated",
        extra={
            "old_key_id": str(old_key.id),
            "new_key_id": str(new_key.id),
            "workspace_id": str(new_key.workspace_id),
            "user_id": str(current_user.id),
        },
    )
    return McpApiKeyCreatedResponse(
        id=new_key.id,
        organization_id=new_key.organization_id,
        workspace_id=new_key.workspace_id,
        name=new_key.name,
        key=raw_key,
        key_prefix=new_key.key_prefix,
        status=McpApiKeyStatus(new_key.status),
        created_by=new_key.created_by,
        created_at=new_key.created_at,
        expires_at=new_key.expires_at,
    )