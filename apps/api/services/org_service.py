from __future__ import annotations

import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from apps.api.models.organization import Organization
from apps.api.models.org_member import OrgMember


async def create_organization(
    db: AsyncSession,
    name: str,
    slug: str,
    description: str | None,
    owner_id: uuid.UUID
) -> Organization:
    """Create a new Organization and assign the creator as the Owner member."""
    org = Organization(
        name=name,
        slug=slug,
        description=description,
        owner_id=owner_id
    )
    db.add(org)
    await db.flush()  # populate org.id

    # Create owner membership
    membership = OrgMember(
        user_id=owner_id,
        organization_id=org.id,
        role="owner"
    )
    db.add(membership)
    await db.commit()
    await db.refresh(org)
    return org


async def get_user_organizations(db: AsyncSession, user_id: uuid.UUID) -> list[Organization]:
    """Retrieve all organizations where the user has active membership."""
    stmt = (
        select(Organization)
        .join(OrgMember, OrgMember.organization_id == Organization.id)
        .where(OrgMember.user_id == user_id)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_organization_by_slug(db: AsyncSession, slug: str) -> Organization | None:
    """Retrieve an organization by slug."""
    stmt = select(Organization).where(Organization.slug == slug)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
