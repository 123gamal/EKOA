"""MCP API key management schemas.

An MCP API key is a high-entropy bearer token scoped to one workspace. The
plaintext value is returned exactly once (on creation); only its SHA-256 hash,
an identifying prefix, and lifecycle metadata are ever persisted.
"""

from __future__ import annotations

import secrets

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Raw key format: ekoa_<org8>_<ws8>_<48 hex chars>. High entropy means the
# SHA-256 hash stored at rest needs no per-key salt (there is nothing low-
# entropy to brute-force), and the prefix lets admins identify a key in lists
# without revealing the secret.
KEY_PREFIX = "ekoa_"


def generate_mcp_api_key(organization_id: UUID, workspace_id: UUID) -> str:
    """Generate a high-entropy MCP API key for an organization/workspace."""
    return f"{KEY_PREFIX}{str(organization_id)[:8]}_{str(workspace_id)[:8]}_{secrets.token_hex(24)}"


class McpApiKeyStatus(str, Enum):
    """Lifecycle states for an MCP API key."""

    ACTIVE = "active"
    REVOKED = "revoked"


class McpApiKeyCreateRequest(BaseModel):
    """Payload for creating a new MCP API key."""

    name: str = Field(..., min_length=1, max_length=255, description="Human-readable label for the key")
    workspace_id: UUID
    expires_in_days: int | None = Field(
        default=None,
        ge=1,
        description="Optional TTL in days. Omit/null for a key that never expires.",
    )


class McpApiKeyCreatedResponse(BaseModel):
    """Returned ONCE at creation: includes the one-time plaintext key.

    The plaintext is not stored and can never be retrieved again; admins
    listing or reading a key afterwards only ever see the prefix + hash.
    """

    id: UUID
    organization_id: UUID
    workspace_id: UUID
    name: str
    key: str = Field(..., description="One-time plaintext API key — shown only here")
    key_prefix: str
    status: McpApiKeyStatus
    created_by: UUID
    created_at: datetime
    expires_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class McpApiKeyResponse(BaseModel):
    """Serialised key metadata returned by list/read endpoints.

    Deliberately does NOT expose the plaintext key or its full hash.
    """

    id: UUID
    organization_id: UUID
    workspace_id: UUID
    name: str
    key_prefix: str
    status: McpApiKeyStatus
    created_by: UUID
    created_at: datetime
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    revoked_by: UUID | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)