"""Tool implementations for the EKOA MCP server.

Both tools are tenant-scoped: the authenticated MCP API key pins the
organization + workspace, and every lookup is filtered through them. Each
tool call records a structured log line, writes an audit entry, and bumps
``last_used_at`` on the key.
"""

from __future__ import annotations

import asyncio
import base64
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select

from apps.api.models.document import Document
from apps.api.models.mcp_api_key import McpApiKey
from apps.api.services import audit_service
from apps.mcp_server.db import get_mcp_session_factory
from ekoa_config.logging import get_correlation_id, get_logger
from ekoa_utils.naming import workspace_collection_name

logger = get_logger("mcp.tools")

MAX_TOOL_RESULTS = 100


class McpIdentity:
    """Tenant identity carried by an authenticated MCP request."""

    def __init__(self, key_id: uuid.UUID, organization_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
        self.key_id = key_id
        self.organization_id = organization_id
        self.workspace_id = workspace_id


def current_identity() -> McpIdentity:
    """Extract the authenticated identity from the MCP auth context.

    Raises ``ToolError`` (which the SDK surfaces to the client) when there is
    no valid authenticated bearer token or the claims are incomplete.
    """
    from mcp.server.auth.middleware.auth_context import get_access_token
    from mcp.server.mcpserver.exceptions import ToolError

    token = get_access_token()
    if token is None:
        raise ToolError("Missing or invalid MCP API key")
    claims = token.claims or {}
    key_id = claims.get("key_id")
    org_id = claims.get("organization_id")
    ws_id = claims.get("workspace_id")
    if not (key_id and org_id and ws_id):
        raise ToolError("Invalid MCP API key claims")
    try:
        return McpIdentity(
            key_id=uuid.UUID(key_id),
            organization_id=uuid.UUID(org_id),
            workspace_id=uuid.UUID(ws_id),
        )
    except ValueError as exc:
        raise ToolError("Invalid MCP API key claims") from exc


async def _record_usage(
    identity: McpIdentity,
    tool: str,
    detail: dict,
) -> None:
    """Audit the call, update last_used_at, and emit a structured log line."""
    async with get_mcp_session_factory()() as db:
        stmt = select(McpApiKey).where(McpApiKey.id == identity.key_id)
        key = (await db.execute(stmt)).scalar_one_or_none()
        if key is not None:
            key.last_used_at = datetime.now(timezone.utc)
        await audit_service.log_action(
            db,
            user_id=key.created_by if key is not None else None,
            action="mcp.tool_call",
            resource_type="mcp_api_keys",
            resource_id=identity.key_id,
            details={
                "tool": tool,
                "organization_id": str(identity.organization_id),
                "workspace_id": str(identity.workspace_id),
                **detail,
            },
        )
    logger.info(
        "mcp_tool_call",
        extra={
            "tool": tool,
            "key_id": str(identity.key_id),
            "workspace_id": str(identity.workspace_id),
            "organization_id": str(identity.organization_id),
            "correlation_id": get_correlation_id(),
            **detail,
        },
    )


async def search_knowledge_base(query: str, limit: int = 5) -> dict:
    """Search the workspace's indexed knowledge base and return top chunks.

    Reuses the Phase 4 tenant-scoped retriever (Qdrant + embeddings), pinned
    to the authenticated key's organization + workspace collection.
    """
    identity = current_identity()
    bounded = max(1, min(int(limit), MAX_TOOL_RESULTS))

    from apps.ai import retriever

    chunks = await asyncio.to_thread(
        retriever.retrieve_chunks,
        query,
        collection_name=workspace_collection_name(identity.workspace_id),
        limit=bounded,
        organization_id=str(identity.organization_id),
        workspace_id=str(identity.workspace_id),
    )
    await _record_usage(
        identity,
        tool="search_knowledge_base",
        detail={"query": query, "limit": bounded, "result_count": len(chunks)},
    )
    return {
        "query": query,
        "limit": bounded,
        "workspace_id": str(identity.workspace_id),
        "results": chunks,
    }


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(f"offset:{offset}".encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    from mcp.server.mcpserver.exceptions import ToolError

    try:
        decoded = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        raise ToolError("Invalid cursor") from exc
    if not decoded.startswith("offset:"):
        raise ToolError("Invalid cursor")
    try:
        return max(0, int(decoded[len("offset:"):]))
    except ValueError as exc:
        raise ToolError("Invalid cursor") from exc


async def list_documents(cursor: str | None = None, limit: int = 20) -> dict:
    """List indexed documents in the key's workspace (cursor pagination).

    Returns document metadata (never chunk text) with a ``next_cursor`` to
    page through results, mirroring the Phase 3 pagination envelope style.
    """
    identity = current_identity()
    bounded = max(1, min(int(limit), MAX_TOOL_RESULTS))
    offset = _decode_cursor(cursor)

    async with get_mcp_session_factory()() as db:
        base = select(Document).where(
            Document.workspace_id == identity.workspace_id,
            Document.deleted_at.is_(None),
        )
        total = (
            await db.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()
        stmt = (
            base.order_by(Document.created_at.desc())
            .offset(offset)
            .limit(bounded)
        )
        docs = list((await db.execute(stmt)).scalars().all())

    items = [
        {
            "id": str(d.id),
            "title": d.title,
            "status": d.status,
            "content_type": d.content_type,
            "file_path": d.file_path,
            "source": (d.metadata_json or {}).get("source"),
            "chunk_count": d.chunk_count,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in docs
    ]
    next_offset = offset + len(docs)
    next_cursor = _encode_cursor(next_offset) if next_offset < total else None

    await _record_usage(
        identity,
        tool="list_documents",
        detail={"cursor": cursor, "limit": bounded, "result_count": len(items)},
    )
    return {
        "workspace_id": str(identity.workspace_id),
        "items": items,
        "total": total,
        "offset": offset,
        "limit": bounded,
        "next_cursor": next_cursor,
    }