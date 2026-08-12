from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.engine import get_db
from apps.api.dependencies.auth import get_current_user
from apps.api.dependencies import authz
from apps.api.models.organization import Organization
from apps.api.models.user import User
from apps.api.services import invite_service, audit_service
from ekoa_config.logging import get_logger
from ekoa_types.invite import InviteAcceptRequest, InviteCreateRequest, InviteResponse
from ekoa_types.pagination import DEFAULT_PAGE, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Paginated

router = APIRouter(tags=["Invites"])

logger = get_logger("api.routes.invites")


async def _get_org_or_404(db: AsyncSession, org_id: uuid.UUID) -> Organization:
    stmt = select(Organization).where(
        Organization.id == org_id, Organization.deleted_at.is_(None)
    )
    org = (await db.execute(stmt)).scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return org


@router.post(
    "/api/v1/organizations/{org_id}/invites",
    response_model=InviteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_invite(
    org_id: uuid.UUID,
    data: InviteCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Invite an email address to join the organization. Admin/owner-only."""
    org = await _get_org_or_404(db, org_id)
    await authz.assert_min_role(db, current_user.id, org.id, "admin")

    try:
        invite, _raw_token = await invite_service.create_invite(
            db, org, data.email, data.role, current_user.id
        )
    except Exception:
        logger.exception("invite_create_failed", extra={"organization_id": str(org.id)})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not send the invite email. The invite was not created.",
        )

    await audit_service.log_action(
        db,
        user_id=current_user.id,
        action="invite.create",
        resource_type="org_invites",
        resource_id=invite.id,
        details={"organization_id": str(org.id), "email": data.email, "role": data.role},
        organization_id=org.id,
    )
    logger.info(
        "invite_created",
        extra={"invite_id": str(invite.id), "organization_id": str(org.id)},
    )
    return invite


@router.get(
    "/api/v1/organizations/{org_id}/invites",
    response_model=Paginated[InviteResponse],
)
async def list_invites(
    org_id: uuid.UUID,
    page: int = Query(DEFAULT_PAGE, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List pending invites for the organization. Admin/owner-only."""
    org = await _get_org_or_404(db, org_id)
    await authz.assert_min_role(db, current_user.id, org.id, "admin")

    invites, total = await invite_service.list_invites(
        db, org.id, status_filter="pending", page=page, page_size=page_size
    )
    return Paginated.create(invites, total, page, page_size)


@router.delete(
    "/api/v1/organizations/{org_id}/invites/{invite_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_invite(
    org_id: uuid.UUID,
    invite_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke a pending invite. Admin/owner-only."""
    org = await _get_org_or_404(db, org_id)
    await authz.assert_min_role(db, current_user.id, org.id, "admin")

    invite = await invite_service.get_invite(db, invite_id)
    if invite is None or invite.organization_id != org.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")

    await invite_service.revoke_invite(db, invite)
    await audit_service.log_action(
        db,
        user_id=current_user.id,
        action="invite.revoke",
        resource_type="org_invites",
        resource_id=invite.id,
        details={"organization_id": str(org.id), "email": invite.email},
        organization_id=org.id,
    )
    return None


@router.post("/api/v1/invites/accept", response_model=InviteResponse)
async def accept_invite(
    data: InviteAcceptRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Accept a pending invite (the invite's email must match the caller's)."""
    try:
        invite = await invite_service.accept_invite(db, data.token, current_user)
    except invite_service.InviteAcceptError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    await audit_service.log_action(
        db,
        user_id=current_user.id,
        action="invite.accept",
        resource_type="org_invites",
        resource_id=invite.id,
        details={"organization_id": str(invite.organization_id)},
        organization_id=invite.organization_id,
    )
    return invite
