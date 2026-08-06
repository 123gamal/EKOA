"""Authentication and authorization for the EKOA AI service."""

from __future__ import annotations

import uuid
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ekoa_config.settings import get_settings
from apps.api.db.engine import get_session_factory
from apps.api.models.user import User
from apps.api.models.org_member import OrgMember
from apps.api.models.workspace import Workspace
from apps.api.models.workflow import Workflow  # noqa: F401  # register mapper for User.workflows / Workspace.workflows

settings = get_settings()

bearer_scheme = HTTPBearer(auto_error=False)


def _verify_token(token: str) -> dict | None:
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError:
        return None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> User:
    """Extract and validate the authenticated user from JWT bearer token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise credentials_exception

    payload = _verify_token(credentials.credentials)
    if payload is None:
        raise credentials_exception

    user_id_str: str | None = payload.get("sub")
    if user_id_str is None:
        raise credentials_exception

    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        raise credentials_exception

    async with get_session_factory()() as db:
        stmt = select(User).where(User.id == user_id)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()

        if user is None:
            raise credentials_exception
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Inactive user"
            )
        return user


async def assert_workspace_access_for_user(
    user: User,
    workspace_id: str,
    db: AsyncSession,
) -> None:
    """Raise 403 if the user is not a member of the org owning the workspace."""
    try:
        ws_uuid = uuid.UUID(workspace_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid workspace_id"
        )

    stmt = select(Workspace.organization_id).where(Workspace.id == ws_uuid)
    result = await db.execute(stmt)
    org_id = result.scalar_one_or_none()
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found"
        )

    mstmt = select(OrgMember).where(
        OrgMember.organization_id == org_id,
        OrgMember.user_id == user.id,
    )
    mresult = await db.execute(mstmt)
    if mresult.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this workspace",
        )