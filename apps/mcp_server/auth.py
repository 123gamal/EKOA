"""Bearer-token verification for the EKOA MCP server.

A client authenticates with a workspace-scoped MCP API key. The verifier
re-hashes the presented bearer token and looks it up against the McpApiKey
table: a match on an ACTIVE key yields an AccessToken whose claims carry the
key/org/workspace identity; anything else (unknown key, revoked key, garbage)
is rejected so the MCP endpoint answers with 401.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy import select

from mcp.server.auth.provider import AccessToken

from apps.api.models.mcp_api_key import McpApiKey
from apps.mcp_server.db import get_mcp_session_factory
from ekoa_config.logging import get_logger
from ekoa_types.mcp import McpApiKeyStatus

logger = get_logger("mcp.auth")


def hash_mcp_key(raw_key: str) -> str:
    """SHA-256 hex digest of a raw MCP API key (the only thing persisted)."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


class EkoaTokenVerifier:
    """Protocol-conforming ``TokenVerifier`` for statically issued EKOA keys.

    ``verify_token`` runs on every authenticated MCP request via the SDK's
    ``BearerAuthBackend``. It performs a single equality lookup on the
    (indexed) ``key_hash`` column, so invalid tokens are cheap to reject and
    revocation is honoured immediately — there is no token cache to flush.
    """

    def __init__(self) -> None:
        pass

    async def verify_token(self, token: str) -> AccessToken | None:
        digest = hash_mcp_key(token)
        async with get_mcp_session_factory()() as db:
            stmt = select(McpApiKey).where(McpApiKey.key_hash == digest)
            key = (await db.execute(stmt)).scalar_one_or_none()

        if key is None:
            return None

        if key.status != McpApiKeyStatus.ACTIVE.value:
            logger.warning(
                "mcp_key_rejected",
                extra={"key_id": str(key.id), "reason": "revoked_or_inactive"},
            )
            return None

        if key.expires_at is not None and key.expires_at <= datetime.now(timezone.utc):
            logger.warning(
                "mcp_key_rejected",
                extra={"key_id": str(key.id), "reason": "expired"},
            )
            return None

        return AccessToken(
            token=token,
            client_id=str(key.id),
            scopes=[],
            subject=str(key.created_by),
            claims={
                "key_id": str(key.id),
                "organization_id": str(key.organization_id),
                "workspace_id": str(key.workspace_id),
                "name": key.name,
            },
        )