from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.engine import get_db
from apps.api.dependencies.auth import get_current_user
from apps.api.models.user import User
from apps.api.services import auth_service, audit_service
from apps.api.core.security import create_access_token, create_refresh_token
from ekoa_types.auth import RegisterRequest, LoginRequest, TokenPair
from ekoa_types.user import UserResponse

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    register_data: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Register a new user in EKOA."""
    user = await auth_service.register_user(db, register_data)
    await audit_service.log_action(
        db,
        user_id=user.id,
        action="user.register",
        resource_type="users",
        resource_id=user.id,
        ip_address=request.client.host if request.client else None
    )
    return user


@router.post("/login", response_model=TokenPair)
async def login(
    login_data: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Authenticate credentials and return a token pair."""
    user = await auth_service.authenticate_user(db, login_data.email, login_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})

    await auth_service.create_user_session(
        db,
        user_id=user.id,
        refresh_token=refresh_token,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )

    await audit_service.log_action(
        db,
        user_id=user.id,
        action="user.login",
        ip_address=request.client.host if request.client else None
    )

    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer"
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    body: dict,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Rotate an old refresh token for a new token pair."""
    old_refresh_token = body.get("refresh_token")
    if not old_refresh_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="refresh_token field is required"
        )

    tokens = await auth_service.rotate_refresh_token(
        db,
        old_refresh_token=old_refresh_token,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )

    if not tokens:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token"
        )

    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Revoke a refresh token to logout."""
    refresh_token = body.get("refresh_token")
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="refresh_token field is required"
        )

    await auth_service.revoke_session(db, refresh_token)
    await audit_service.log_action(
        db,
        user_id=current_user.id,
        action="user.logout"
    )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """Retrieve the current user's profile."""
    return current_user
