"""Org invite schemas (Phase 13 — team collaboration).

An invite is a high-entropy bearer token embedded in an email link. The
plaintext value is only ever present in that email; only its SHA-256 hash and
lifecycle metadata are persisted, mirroring how MCP API keys are handled
(see ``ekoa_types.mcp``).
"""

from __future__ import annotations

import secrets

from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

INVITE_TOKEN_BYTES = 32

# Owners are never created via invite — only by org creation or an explicit
# ownership transfer (not built in this phase). This keeps a leaked invite
# link from ever being able to mint a second owner.
InviteRole = Literal["admin", "member"]


def generate_invite_token() -> str:
    """Generate a high-entropy, URL-safe org invite token."""
    return secrets.token_urlsafe(INVITE_TOKEN_BYTES)


class InviteStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"


class InviteCreateRequest(BaseModel):
    """Payload for inviting an email address to an organization."""

    email: EmailStr
    role: InviteRole = "member"


class InviteResponse(BaseModel):
    """Serialised invite metadata. Never includes the raw token."""

    id: UUID
    organization_id: UUID
    email: str
    role: str
    status: InviteStatus
    invited_by: UUID
    expires_at: datetime
    accepted_at: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InviteAcceptRequest(BaseModel):
    """Payload for accepting an invite by its raw token."""

    token: str = Field(..., min_length=1)
