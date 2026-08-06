from __future__ import annotations

import uuid
from datetime import timedelta, timezone
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from apps.api.models.user import User
from apps.api.models.session import UserSession
from apps.api.models.organization import Organization
from apps.api.models.org_member import OrgMember
from apps.api.models.workspace import Workspace
from apps.api.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    verify_token
)
from ekoa_types.auth import RegisterRequest, TokenPair
from ekoa_config.settings import get_settings
from ekoa_utils.datetime_utils import utc_now

settings = get_settings()


def _slugify(name: str) -> str:
    """Build a URL-safe slug from an organization name."""
    slug = "".join(c.lower() if c.isalnum() else "-" for c in name).strip("-")
    slug = "-".join(p for p in slug.split("-") if p)
    return slug or "organization"


async def register_user(db: AsyncSession, register_data: RegisterRequest) -> User:
    """Register a new user inside the system after checking email uniqueness."""
    # Check email exists
    stmt = select(User).where(User.email == register_data.email)
    result = await db.execute(stmt)
    existing_user = result.scalar_one_or_none()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered"
        )

    hashed_pw = hash_password(register_data.password)
    user = User(
        email=register_data.email,
        full_name=register_data.full_name,
        hashed_password=hashed_pw,
    )
    db.add(user)
    await db.flush()  # populate user.id

    # Optionally create an initial organization + workspace + membership.
    if register_data.organization_name:
        org_name = register_data.organization_name.strip()
        if org_name:
            base_slug = _slugify(org_name)
            slug = base_slug
            suffix = 1
            while await _org_slug_exists(db, slug):
                slug = f"{base_slug}-{suffix}"
                suffix += 1

            org = Organization(
                name=org_name,
                slug=slug,
                owner_id=user.id,
            )
            db.add(org)
            await db.flush()

            db.add(OrgMember(
                user_id=user.id,
                organization_id=org.id,
                role="owner",
            ))

            workspace = Workspace(
                name="Default Workspace",
                organization_id=org.id,
                created_by=user.id,
            )
            db.add(workspace)

    await db.commit()
    await db.refresh(user)
    return user


async def _org_slug_exists(db: AsyncSession, slug: str) -> bool:
    stmt = select(Organization).where(Organization.slug == slug)
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User | None:
    """Find a user by email and verify password hash."""
    stmt = select(User).where(User.email == email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


async def create_user_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    refresh_token: str,
    ip_address: str | None = None,
    user_agent: str | None = None
) -> UserSession:
    """Record a new JWT refresh token session."""
    expires_at = utc_now() + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    session = UserSession(
        user_id=user_id,
        refresh_token=refresh_token,
        expires_at=expires_at,
        ip_address=ip_address,
        user_agent=user_agent
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def revoke_session(db: AsyncSession, refresh_token: str) -> None:
    """Revoke an existing session refresh token."""
    stmt = select(UserSession).where(UserSession.refresh_token == refresh_token)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if session:
        session.is_revoked = True
        await db.commit()


async def rotate_refresh_token(
    db: AsyncSession,
    old_refresh_token: str,
    ip_address: str | None = None,
    user_agent: str | None = None
) -> TokenPair | None:
    """Validate old refresh token, revoke it, and issue a new access/refresh token pair."""
    # Find session
    stmt = select(UserSession).where(UserSession.refresh_token == old_refresh_token)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()

    if not session or session.is_revoked or (session.expires_at.replace(tzinfo=timezone.utc) if session.expires_at.tzinfo is None else session.expires_at) < utc_now():
        return None

    # Revoke old session
    session.is_revoked = True

    # Decode old token payload
    payload = verify_token(old_refresh_token)
    if not payload:
        await db.commit()
        return None

    user_id_str = payload.get("sub")
    if not user_id_str:
        await db.commit()
        return None

    user_id = uuid.UUID(user_id_str)

    # Issue new tokens
    access_token = create_access_token(data={"sub": str(user_id)})
    new_refresh_token = create_refresh_token(data={"sub": str(user_id)})

    # Create new session
    new_session = UserSession(
        user_id=user_id,
        refresh_token=new_refresh_token,
        expires_at=utc_now() + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
        ip_address=ip_address,
        user_agent=user_agent
    )
    db.add(new_session)
    await db.commit()

    return TokenPair(
        access_token=access_token,
        refresh_token=new_refresh_token,
        token_type="bearer"
    )
