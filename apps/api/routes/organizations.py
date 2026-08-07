from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select

from apps.api.db.engine import get_db
from apps.api.dependencies.auth import get_current_user
from apps.api.dependencies import authz
from apps.api.models.user import User
from apps.api.models.organization import Organization
from apps.api.models.org_member import OrgMember
from apps.api.services import org_service, audit_service
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
        details={"name": org.name, "slug": org.slug}
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
        .where(OrgMember.user_id == current_user.id)
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
