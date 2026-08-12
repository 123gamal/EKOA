from __future__ import annotations

import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select

from apps.api.db.engine import get_db
from apps.api.dependencies.auth import get_current_user
from apps.api.dependencies import authz
from apps.api.models.user import User
from apps.api.models.organization import Organization
from apps.api.models.org_member import OrgMember
from apps.api.services import org_service, audit_service, invite_service
from ekoa_types.member import MemberRoleUpdateRequest, OrgMemberResponse
from ekoa_types.organization import OrganizationCreate, OrganizationResponse
from ekoa_types.pagination import (
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    Paginated,
)

router = APIRouter(prefix="/api/v1/organizations", tags=["Organizations"])


@router.post("/", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_org(
    org_data: OrganizationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new Organization and set the current user as the Owner."""
    # Check if slug exists
    existing_org = await org_service.get_organization_by_slug(db, org_data.slug)
    if existing_org:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Organization with slug '{org_data.slug}' already exists."
        )

    org = await org_service.create_organization(
        db,
        name=org_data.name,
        slug=org_data.slug,
        description=org_data.description,
        owner_id=current_user.id
    )

    await audit_service.log_action(
        db,
        user_id=current_user.id,
        action="organization.create",
        resource_type="organizations",
        resource_id=org.id,
        details={"name": org.name, "slug": org.slug},
        organization_id=org.id,
    )

    return org


@router.get("/", response_model=Paginated[OrganizationResponse])
async def list_orgs(
    page: int = Query(DEFAULT_PAGE, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Items per page"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List all organizations where the current user has active membership (paginated)."""
    base = (
        select(Organization)
        .join(OrgMember, OrgMember.organization_id == Organization.id)
        .where(
            OrgMember.user_id == current_user.id,
            Organization.deleted_at.is_(None),
        )
    )
    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()

    stmt = base.order_by(Organization.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    items = list((await db.execute(stmt)).scalars().all())
    return Paginated.create(items, total, page, page_size)


@router.get("/{slug}", response_model=OrganizationResponse)
async def get_org(
    slug: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve details for a specific organization by slug."""
    org = await org_service.get_organization_by_slug(db, slug)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )

    await authz.assert_org_membership(db, current_user.id, org.id)
    return org


@router.delete("/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_org(
    slug: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Soft-delete an organization (owner only). The row is kept with deleted_at set."""
    org = await org_service.get_organization_by_slug(db, slug)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )

    await authz.assert_min_role(db, current_user.id, org.id, "owner")

    org.deleted_at = datetime.now(timezone.utc)
    db.add(org)
    await db.commit()

    await audit_service.log_action(
        db,
        user_id=current_user.id,
        action="organization.delete",
        resource_type="organizations",
        resource_id=org.id,
        details={"name": org.name, "slug": org.slug},
        organization_id=org.id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Member management (Phase 13) ────────────────────────────────────────────


async def _get_org_by_id_or_404(db: AsyncSession, org_id: uuid.UUID) -> Organization:
    stmt = select(Organization).where(
        Organization.id == org_id, Organization.deleted_at.is_(None)
    )
    org = (await db.execute(stmt)).scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return org


@router.get("/{org_id}/members", response_model=Paginated[OrgMemberResponse])
async def list_members(
    org_id: uuid.UUID,
    page: int = Query(DEFAULT_PAGE, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List members of an organization. Any member may view the roster."""
    org = await _get_org_by_id_or_404(db, org_id)
    await authz.assert_org_membership(db, current_user.id, org.id)

    base = (
        select(OrgMember, User)
        .join(User, User.id == OrgMember.user_id)
        .where(OrgMember.organization_id == org.id)
    )
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    stmt = (
        base.order_by(OrgMember.created_at.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(stmt)).all()
    items = [
        OrgMemberResponse(
            user_id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=member.role,
            joined_at=member.created_at,
        )
        for member, user in rows
    ]
    return Paginated.create(items, total, page, page_size)


@router.patch("/{org_id}/members/{user_id}", response_model=OrgMemberResponse)
async def update_member_role(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    data: MemberRoleUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change a member's role. Admin/owner-only; cannot demote the last owner."""
    org = await _get_org_by_id_or_404(db, org_id)
    await authz.assert_min_role(db, current_user.id, org.id, "admin")

    stmt = select(OrgMember).where(
        OrgMember.organization_id == org.id, OrgMember.user_id == user_id
    )
    member = (await db.execute(stmt)).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")

    if member.role == "owner" and await invite_service.count_owners(db, org.id) <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change the role of the organization's last owner",
        )

    member.role = data.role
    await db.commit()
    await db.refresh(member)

    await audit_service.log_action(
        db,
        user_id=current_user.id,
        action="member.role_change",
        resource_type="org_members",
        resource_id=member.id,
        details={"target_user_id": str(user_id), "new_role": data.role},
        organization_id=org.id,
    )

    user_stmt = select(User).where(User.id == user_id)
    user = (await db.execute(user_stmt)).scalar_one()
    return OrgMemberResponse(
        user_id=user.id, email=user.email, full_name=user.full_name,
        role=member.role, joined_at=member.created_at,
    )


@router.delete("/{org_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a member from the organization. Admin/owner-only; cannot remove the last owner."""
    org = await _get_org_by_id_or_404(db, org_id)
    await authz.assert_min_role(db, current_user.id, org.id, "admin")

    stmt = select(OrgMember).where(
        OrgMember.organization_id == org.id, OrgMember.user_id == user_id
    )
    member = (await db.execute(stmt)).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")

    if member.role == "owner" and await invite_service.count_owners(db, org.id) <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove the organization's last owner",
        )

    await db.delete(member)
    await db.commit()

    await audit_service.log_action(
        db,
        user_id=current_user.id,
        action="member.remove",
        resource_type="org_members",
        resource_id=None,
        details={"target_user_id": str(user_id)},
        organization_id=org.id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
