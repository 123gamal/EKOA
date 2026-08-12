"""Org member management schemas (Phase 13 — team collaboration)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

# 'owner' is included for read responses (an org always has one) but role
# changes are restricted to admin/member — ownership transfer is not built
# in this phase, so an owner can't be demoted or overwritten via this route.
MemberRole = Literal["owner", "admin", "member"]


class OrgMemberResponse(BaseModel):
    """A member of an organization, with their user identity flattened in."""

    user_id: UUID
    email: str
    full_name: str
    role: MemberRole
    joined_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MemberRoleUpdateRequest(BaseModel):
    """Payload for changing a member's role. Cannot target 'owner'."""

    role: Literal["admin", "member"]
