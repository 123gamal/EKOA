from __future__ import annotations

import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from apps.api.db.engine import get_db
from apps.api.dependencies.auth import get_current_user
from apps.api.dependencies import authz
from apps.api.models.user import User
from apps.api.models.connector import Connector, ConnectorCredential
from apps.api.services import audit_service
from apps.api.services.connectors.base import (
    ConnectorError,
    ConnectorValidationError,
    get_connector_adapter,
)
from ekoa_config.logging import get_correlation_id, get_logger
from ekoa_config.connector_crypto import encrypt_secret
from ekoa_types.connector import (
    ConnectorConnectRequest,
    ConnectorHealthResponse,
    ConnectorLastSyncStatus,
    ConnectorResponse,
    ConnectorStatus,
    ConnectorSyncResponse,
)
from ekoa_types.pagination import (
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    Paginated,
)

router = APIRouter(prefix="/api/v1/connectors", tags=["Connectors"])

logger = get_logger("api.routes.connectors")


async def _load_active_connector(
    db: AsyncSession, connector_id: uuid.UUID, user: User
) -> Connector:
    """Load a non-deleted connector and verify the caller can access it."""
    stmt = (
        select(Connector)
        .options(selectinload(Connector.credential))
        .where(
            Connector.id == connector_id,
            Connector.deleted_at.is_(None),
        )
    )
    result = await db.execute(stmt)
    connector = result.scalar_one_or_none()
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found"
        )
    await authz.assert_can_access_workspace(connector.workspace_id, user, db)
    return connector


async def _require_admin(
    db: AsyncSession, user: User, connector: Connector
) -> None:
    org_id = await authz.org_id_for_workspace(db, connector.workspace_id)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found"
        )
    await authz.assert_min_role(db, user.id, org_id, "admin")


@router.post("/", response_model=ConnectorResponse, status_code=status.HTTP_201_CREATED)
async def connect_connector(
    data: ConnectorConnectRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Connect an integration. Validates the credential against the provider
    BEFORE saving anything, then stores the token Fernet-encrypted at rest."""
    await authz.assert_can_access_workspace(data.workspace_id, current_user, db)
    org_id = await authz.org_id_for_workspace(db, data.workspace_id)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found"
        )
    await authz.assert_min_role(db, current_user.id, org_id, "admin")

    # Validate first — never persist a credential that fails validation.
    adapter = get_connector_adapter(data.provider)
    try:
        validated_config = adapter.test_connection(
            dict(data.config), data.access_token
        )
    except ConnectorValidationError as exc:
        logger.info(
            "connector_connect_rejected",
            extra={
                "provider": data.provider,
                "workspace_id": str(data.workspace_id),
                "user_id": str(current_user.id),
                "reason": str(exc),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    except ConnectorError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not reach provider: {exc}",
        )

    encrypted_token = encrypt_secret(data.access_token)

    # Re-connect is idempotent per (workspace, provider, repo): if a connector
    # already exists for the same repo, refresh its credential instead of
    # creating a duplicate integration row.
    repo_key = f"{validated_config.get('owner', '')}/{validated_config.get('repo', '')}".strip("/")
    stmt = (
        select(Connector)
        .options(selectinload(Connector.credential))
        .where(
            Connector.workspace_id == data.workspace_id,
            Connector.provider == data.provider,
            Connector.deleted_at.is_(None),
        )
    )
    existing = (await db.execute(stmt)).scalars().all()
    matching = next(
        (
            c
            for c in existing
            if c.name.lower() == data.name.lower() or (
                (c.config_json or {}).get("owner")
                and (c.config_json or {}).get("repo")
                and f"{c.config_json['owner']}/{c.config_json['repo']}".lower()
                == repo_key
            )
        ),
        None,
    )

    if matching is not None:
        connector = matching
        connector.status = ConnectorStatus.CONNECTED.value
        connector.status_reason = None
        connector.connected_by = current_user.id
        connector.connected_at = datetime.now(timezone.utc)
        connector.config_json = validated_config
        if connector.credential is not None:
            connector.credential.access_token_encrypted = encrypted_token
            connector.credential.token_type = "pat"
        else:
            db.add(
                ConnectorCredential(
                    connector_id=connector.id,
                    token_type="pat",
                    access_token_encrypted=encrypted_token,
                )
            )
        await db.commit()
        await db.refresh(connector)
    else:
        connector = Connector(
            organization_id=org_id,
            workspace_id=data.workspace_id,
            provider=data.provider,
            name=data.name,
            status=ConnectorStatus.CONNECTED.value,
            connected_by=current_user.id,
            connected_at=datetime.now(timezone.utc),
            config_json=validated_config,
        )
        db.add(connector)
        await db.flush()
        db.add(
            ConnectorCredential(
                connector_id=connector.id,
                token_type="pat",
                access_token_encrypted=encrypted_token,
            )
        )
        await db.commit()
        await db.refresh(connector)

    await audit_service.log_action(
        db,
        user_id=current_user.id,
        action="connector.connect",
        resource_type="connectors",
        resource_id=connector.id,
        details={
            "provider": connector.provider,
            "name": connector.name,
            "workspace_id": str(connector.workspace_id),
            "config": validated_config,
        },
    )
    logger.info(
        "connector_connected",
        extra={
            "connector_id": str(connector.id),
            "provider": connector.provider,
            "workspace_id": str(connector.workspace_id),
            "user_id": str(current_user.id),
        },
    )
    return connector


@router.post("/{connector_id}/disconnect", response_model=ConnectorResponse)
async def disconnect_connector(
    connector_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Disconnect an integration: remove its stored credential and mark it
    disconnected. Admin-gated and audited."""
    connector = await _load_active_connector(db, connector_id, current_user)
    await _require_admin(db, current_user, connector)

    if connector.credential is not None:
        await db.delete(connector.credential)
    connector.status = ConnectorStatus.DISCONNECTED.value
    connector.status_reason = None
    await db.commit()
    await db.refresh(connector)

    await audit_service.log_action(
        db,
        user_id=current_user.id,
        action="connector.disconnect",
        resource_type="connectors",
        resource_id=connector.id,
        details={
            "provider": connector.provider,
            "name": connector.name,
            "workspace_id": str(connector.workspace_id),
        },
    )
    logger.info(
        "connector_disconnected",
        extra={
            "connector_id": str(connector.id),
            "provider": connector.provider,
            "user_id": str(current_user.id),
        },
    )
    return connector


@router.post("/{connector_id}/sync", response_model=ConnectorSyncResponse)
async def sync_connector(
    connector_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger a manual sync of a connected integration via the worker."""
    connector = await _load_active_connector(db, connector_id, current_user)
    await _require_admin(db, current_user, connector)

    if connector.status != ConnectorStatus.CONNECTED.value or connector.credential is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Connector is not connected (no credential stored)",
        )

    connector.last_sync_status = ConnectorLastSyncStatus.RUNNING.value
    await db.commit()

    await audit_service.log_action(
        db,
        user_id=current_user.id,
        action="connector.sync_triggered",
        resource_type="connectors",
        resource_id=connector.id,
        details={
            "provider": connector.provider,
            "name": connector.name,
            "workspace_id": str(connector.workspace_id),
        },
    )
    logger.info(
        "connector_sync_triggered",
        extra={
            "connector_id": str(connector.id),
            "provider": connector.provider,
            "user_id": str(current_user.id),
            "correlation_id": get_correlation_id(),
        },
    )

    # Enqueue the worker task. A failed enqueue is visible (running → error),
    # never silently swallowed.
    try:
        from apps.worker.tasks import sync_github_connector

        sync_github_connector.delay(
            str(connector.id), correlation_id=get_correlation_id()
        )
    except Exception as exc:  # noqa: BLE001
        connector.last_sync_status = ConnectorLastSyncStatus.FAILED.value
        connector.last_sync_error = f"enqueue_failed: {type(exc).__name__}: {exc}"
        await db.commit()
        logger.error(
            "connector_sync_enqueue_failed",
            extra={"connector_id": str(connector.id), "error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to enqueue sync task; worker may be unavailable",
        )

    return ConnectorSyncResponse(
        id=connector.id,
        status="sync_triggered",
        detail="Sync task enqueued",
    )


@router.get("/", response_model=Paginated[ConnectorResponse])
async def list_connectors(
    workspace_id: uuid.UUID = Query(...),
    page: int = Query(DEFAULT_PAGE, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List integrations connected inside a workspace (paginated, latest first)."""
    await authz.assert_can_access_workspace(workspace_id, current_user, db)

    base = select(Connector).where(
        Connector.workspace_id == workspace_id,
        Connector.deleted_at.is_(None),
    )
    count = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()

    stmt = (
        base.order_by(Connector.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list((await db.execute(stmt)).scalars().all())
    return Paginated.create(items, count, page, page_size)


@router.get("/{connector_id}", response_model=ConnectorResponse)
async def get_connector(
    connector_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a single connector's metadata (never its credential)."""
    return await _load_active_connector(db, connector_id, current_user)


@router.get("/{connector_id}/health", response_model=ConnectorHealthResponse)
async def connector_health(
    connector_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Real health check: verify the stored credential against the provider
    and report the last sync outcome — not just row existence."""
    connector = await _load_active_connector(db, connector_id, current_user)
    adapter = get_connector_adapter(connector.provider)

    connector_status = {
        "last_sync_status": connector.last_sync_status,
        "last_sync_error": connector.last_sync_error,
        "last_sync_at": (
            connector.last_sync_at.isoformat() if connector.last_sync_at else None
        ),
    }

    token_valid = False
    detail = "No credential stored — connector is disconnected"
    if connector.credential is not None:
        try:
            from ekoa_config.connector_crypto import decrypt_secret

            token = decrypt_secret(connector.credential.access_token_encrypted)
            health = adapter.health_check(
                connector.config_json or {}, token, connector_status
            )
            token_valid = health.token_valid
            detail = health.detail
        except ValueError as exc:
            detail = str(exc)
        except ConnectorError as exc:
            detail = str(exc)

    # Reflect reality: a revoked/invalid token flips the connector to error so
    # the UI and observability surface the broken state rather than hiding it.
    if not token_valid and connector.status == ConnectorStatus.CONNECTED.value:
        connector.status = ConnectorStatus.ERROR.value
        connector.status_reason = detail
        await db.commit()
        await db.refresh(connector)

    logger.info(
        "connector_health",
        extra={
            "connector_id": str(connector.id),
            "provider": connector.provider,
            "token_valid": token_valid,
            "status": connector.status,
        },
    )
    return ConnectorHealthResponse(
        id=connector.id,
        provider=connector.provider,
        name=connector.name,
        status=ConnectorStatus(connector.status),
        token_valid=token_valid,
        detail=detail,
        last_sync_at=connector.last_sync_at,
        last_sync_status=(
            ConnectorLastSyncStatus(connector.last_sync_status)
            if connector.last_sync_status
            else None
        ),
        last_sync_error=connector.last_sync_error,
    )
