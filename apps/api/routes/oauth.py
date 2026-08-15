from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.core.security import create_access_token, verify_token
from apps.api.db.engine import get_db
from apps.api.dependencies.auth import get_current_user
from apps.api.dependencies import authz
from apps.api.models.connector import Connector, ConnectorCredential
from apps.api.models.user import User
from apps.api.services import audit_service
from apps.api.services.connectors.base import (
    ConnectorError,
    ConnectorValidationError,
    get_connector_adapter,
)
from ekoa_config.connector_crypto import encrypt_secret
from ekoa_config.logging import get_logger
from ekoa_config.settings import get_settings
from ekoa_types.connector import ConnectorStatus

router = APIRouter(prefix="/api/v1/connectors/oauth", tags=["Connectors"])

logger = get_logger("api.routes.oauth")

STATE_PURPOSE = "connector_oauth_state"
STATE_TTL_MINUTES = 10


@router.get("/{provider}/authorize")
async def oauth_authorize(
    provider: str,
    workspace_id: uuid.UUID = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the provider's consent-screen URL for the frontend to navigate to.

    This is a normal authenticated JSON endpoint, NOT a redirect: a bare
    browser navigation here couldn't carry the Authorization header the way
    ``apiFetch`` does, so the frontend calls this via a real authenticated
    request and does ``window.location.href = authorize_url`` itself.
    Admin-gated the same way the manual PAT connect flow is — connecting an
    integration is a privileged, workspace-admin action either way.
    """
    await authz.assert_can_access_workspace(workspace_id, current_user, db)
    org_id = await authz.org_id_for_workspace(db, workspace_id)
    if org_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    await authz.assert_min_role(db, current_user.id, org_id, "admin")

    try:
        adapter = get_connector_adapter(provider)
    except ConnectorValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if adapter.auth_type != "oauth2":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'{provider}' does not use OAuth2 — connect it with an access token instead",
        )

    state = create_access_token(
        data={
            "purpose": STATE_PURPOSE,
            "provider": provider,
            "workspace_id": str(workspace_id),
            "user_id": str(current_user.id),
        },
        expires_delta=timedelta(minutes=STATE_TTL_MINUTES),
    )
    return {"authorize_url": adapter.oauth_authorize_url(state, workspace_id=str(workspace_id))}


@router.get("/{provider}/callback")
async def oauth_callback(
    provider: str,
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Provider redirects the user's browser back here after consent.

    No Authorization header is present on this request (it's a bare browser
    redirect) — the caller's identity comes entirely from the signed state
    token minted in :func:`oauth_authorize`, not from a bearer token.
    """
    settings = get_settings()
    frontend = settings.FRONTEND_URL.rstrip("/")

    if error:
        logger.info("oauth_denied", extra={"provider": provider, "error": error})
        return RedirectResponse(f"{frontend}/settings?connector={provider}&status=denied")

    if not code or not state:
        return RedirectResponse(f"{frontend}/settings?connector={provider}&status=error")

    payload = verify_token(state)
    if (
        not payload
        or payload.get("purpose") != STATE_PURPOSE
        or payload.get("provider") != provider
    ):
        logger.warning("oauth_invalid_state", extra={"provider": provider})
        return RedirectResponse(f"{frontend}/settings?connector={provider}&status=error")

    workspace_id = uuid.UUID(payload["workspace_id"])
    user_id = uuid.UUID(payload["user_id"])

    org_id = await authz.org_id_for_workspace(db, workspace_id)
    if org_id is None:
        return RedirectResponse(f"{frontend}/settings?connector={provider}&status=error")

    try:
        adapter = get_connector_adapter(provider)
        token_result = adapter.oauth_exchange_code(code)
        validated_config = dict(token_result.config)
        try:
            # Enrich with whatever test_connection can add (e.g. Google's
            # account email) — a failure here isn't fatal, the token from
            # the exchange step is already known-good.
            validated_config = {
                **validated_config,
                **adapter.test_connection(validated_config, token_result.access_token),
            }
        except ConnectorError:
            pass
    except ConnectorError as exc:
        logger.error(
            "oauth_exchange_failed", extra={"provider": provider, "error": str(exc)}
        )
        return RedirectResponse(f"{frontend}/settings?connector={provider}&status=error")

    identity = adapter.identity_key(validated_config)
    stmt = (
        select(Connector)
        .options(selectinload(Connector.credential))
        .where(
            Connector.workspace_id == workspace_id,
            Connector.provider == provider,
            Connector.deleted_at.is_(None),
        )
    )
    existing = (await db.execute(stmt)).scalars().all()
    matching = next(
        (
            c
            for c in existing
            if identity is not None and adapter.identity_key(c.config_json or {}) == identity
        ),
        None,
    )

    encrypted_access = encrypt_secret(token_result.access_token)
    encrypted_refresh = (
        encrypt_secret(token_result.refresh_token) if token_result.refresh_token else None
    )
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=token_result.expires_in)
        if token_result.expires_in
        else None
    )
    display_name = (
        validated_config.get("team_name")
        or validated_config.get("account")
        or validated_config.get("title")
        or provider
    )

    if matching is not None:
        connector = matching
        connector.status = ConnectorStatus.CONNECTED.value
        connector.status_reason = None
        connector.connected_by = user_id
        connector.connected_at = datetime.now(timezone.utc)
        connector.config_json = validated_config
        if connector.credential is not None:
            connector.credential.access_token_encrypted = encrypted_access
            connector.credential.refresh_token_encrypted = encrypted_refresh
            connector.credential.token_expires_at = expires_at
            connector.credential.token_type = "oauth2"
        else:
            db.add(
                ConnectorCredential(
                    connector_id=connector.id,
                    token_type="oauth2",
                    access_token_encrypted=encrypted_access,
                    refresh_token_encrypted=encrypted_refresh,
                    token_expires_at=expires_at,
                )
            )
    else:
        connector = Connector(
            organization_id=org_id,
            workspace_id=workspace_id,
            provider=provider,
            name=str(display_name),
            status=ConnectorStatus.CONNECTED.value,
            connected_by=user_id,
            connected_at=datetime.now(timezone.utc),
            config_json=validated_config,
        )
        db.add(connector)
        await db.flush()
        db.add(
            ConnectorCredential(
                connector_id=connector.id,
                token_type="oauth2",
                access_token_encrypted=encrypted_access,
                refresh_token_encrypted=encrypted_refresh,
                token_expires_at=expires_at,
            )
        )

    await db.commit()
    await db.refresh(connector)

    await audit_service.log_action(
        db,
        user_id=user_id,
        action="connector.connect",
        resource_type="connectors",
        resource_id=connector.id,
        details={"provider": provider, "name": connector.name, "workspace_id": str(workspace_id), "via": "oauth2"},
        organization_id=org_id,
    )
    logger.info(
        "connector_oauth_connected",
        extra={"connector_id": str(connector.id), "provider": provider, "workspace_id": str(workspace_id)},
    )
    return RedirectResponse(f"{frontend}/settings?connector={provider}&status=ok")
