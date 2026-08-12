from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.organization import Organization
from apps.api.models.org_invite import OrgInvite
from apps.api.models.org_member import OrgMember
from apps.api.models.user import User
from apps.api.services import email_service
from ekoa_config.settings import get_settings
from ekoa_types.invite import generate_invite_token

INVITE_EXPIRY_DAYS = 7


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _invite_email_html(org_name: str, role: str, accept_url: str) -> str:
    return (
        f"<p>You've been invited to join <strong>{org_name}</strong> on EKOA "
        f"as a <strong>{role}</strong>.</p>"
        f'<p><a href="{accept_url}">Accept invite</a></p>'
        f"<p>This link expires in {INVITE_EXPIRY_DAYS} days. If you weren't "
        f"expecting this, you can ignore this email.</p>"
    )


async def create_invite(
    db: AsyncSession,
    organization: Organization,
    email: str,
    role: str,
    invited_by: uuid.UUID,
) -> tuple[OrgInvite, str]:
    """Create a pending invite and send the invite email.

    Returns the persisted invite and the raw token (present in memory only —
    never persisted, only ever embedded in the email that was just sent).
    """
    settings = get_settings()
    raw_token = generate_invite_token()
    invite = OrgInvite(
        organization_id=organization.id,
        email=email,
        role=role,
        token_hash=_hash_token(raw_token),
        status="pending",
        invited_by=invited_by,
        expires_at=datetime.now(timezone.utc) + timedelta(days=INVITE_EXPIRY_DAYS),
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)

    accept_url = f"{settings.FRONTEND_URL}/accept-invite?token={raw_token}"
    await email_service.send_email(
        to=email,
        subject=f"You're invited to join {organization.name} on EKOA",
        html_body=_invite_email_html(organization.name, role, accept_url),
    )

    return invite, raw_token


async def list_invites(
    db: AsyncSession,
    organization_id: uuid.UUID,
    *,
    status_filter: str | None = "pending",
    page: int = 1,
    page_size: int = 25,
) -> tuple[list[OrgInvite], int]:
    base = select(OrgInvite).where(OrgInvite.organization_id == organization_id)
    if status_filter is not None:
        base = base.where(OrgInvite.status == status_filter)

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()

    stmt = base.order_by(OrgInvite.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    items = list((await db.execute(stmt)).scalars().all())
    return items, total


async def get_invite(db: AsyncSession, invite_id: uuid.UUID) -> OrgInvite | None:
    stmt = select(OrgInvite).where(OrgInvite.id == invite_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def revoke_invite(db: AsyncSession, invite: OrgInvite) -> OrgInvite:
    invite.status = "revoked"
    await db.commit()
    await db.refresh(invite)
    return invite


class InviteAcceptError(Exception):
    """Raised for any invalid accept attempt; message is safe to show the caller."""


async def accept_invite(db: AsyncSession, raw_token: str, current_user: User) -> OrgInvite:
    """Validate an invite token and create the corresponding org membership.

    Requires the caller to already be authenticated as a user whose email
    matches the invite (no combined register+accept flow in this phase — the
    user registers/logs in normally first). Returns the now-accepted invite.
    """
    token_hash = _hash_token(raw_token)
    stmt = select(OrgInvite).where(OrgInvite.token_hash == token_hash)
    invite = (await db.execute(stmt)).scalar_one_or_none()

    if invite is None:
        raise InviteAcceptError("Invalid or unknown invite token")
    if invite.status != "pending":
        raise InviteAcceptError(f"This invite has already been {invite.status}")
    # SQLite (used in tests) returns naive datetimes even for TZ-aware
    # columns; Postgres does not. Normalize before comparing, same pattern as
    # auth_service._is_session_expired.
    expires_at = (
        invite.expires_at.replace(tzinfo=timezone.utc)
        if invite.expires_at.tzinfo is None
        else invite.expires_at
    )
    if expires_at < datetime.now(timezone.utc):
        raise InviteAcceptError("This invite has expired")
    if invite.email.lower() != current_user.email.lower():
        raise InviteAcceptError(
            "This invite was sent to a different email address than your account"
        )

    existing = (
        await db.execute(
            select(OrgMember).where(
                OrgMember.organization_id == invite.organization_id,
                OrgMember.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            OrgMember(
                user_id=current_user.id,
                organization_id=invite.organization_id,
                role=invite.role,
            )
        )

    invite.status = "accepted"
    invite.accepted_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(invite)
    return invite


async def count_owners(db: AsyncSession, organization_id: uuid.UUID) -> int:
    stmt = select(func.count()).select_from(OrgMember).where(
        OrgMember.organization_id == organization_id,
        OrgMember.role == "owner",
    )
    return (await db.execute(stmt)).scalar_one()
