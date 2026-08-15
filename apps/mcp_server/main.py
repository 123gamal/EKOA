"""EKOA MCP Server — two tenant-scoped tools over Streamable HTTP.

``create_server()`` builds an ``MCPServer`` wired with ``AuthSettings`` +
``EkoaTokenVerifier`` so every MCP request must present a valid, active
workspace-scoped MCP API key. The ``/health`` liveness route is exempt from
auth (custom routes are never wrapped by ``RequireAuthMiddleware``).

Transport: Streamable HTTP (``/mcp``). SSE is the 2025-03-26 protocol
revision's superseded predecessor, so new deployments must not build on it.
"""

from __future__ import annotations

from sqlalchemy import text
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver.server import MCPServer

from apps.mcp_server.auth import EkoaTokenVerifier
from apps.mcp_server.db import get_mcp_session_factory
from apps.mcp_server.tools import (
    get_workflow_status,
    list_documents,
    query_analytics,
    search_knowledge_base,
)
from ekoa_config.logging import get_logger, setup_logging
from ekoa_config.settings import get_settings

setup_logging("mcp")
settings = get_settings()
logger = get_logger("mcp.main")

_SEARCH_DESCRIPTION = (
    "Search the authenticated workspace's indexed knowledge base and return "
    "the top relevant chunks with similarity scores. Use this to ground "
    "answers in the organization's own documents (connector-synced content)."
)

_LIST_DESCRIPTION = (
    "List documents (metadata only, never chunk text) currently indexed in "
    "the authenticated workspace. Paginate with the returned next_cursor."
)

_WORKFLOW_STATUS_DESCRIPTION = (
    "Report the authenticated workspace's workflows and each one's latest run "
    "status (including approval-pending state). Read-only; does not trigger "
    "or modify any workflow run."
)

_ANALYTICS_DESCRIPTION = (
    "Summarize the authenticated workspace's AI usage (call count, average "
    "latency, token totals, estimated cost) and document counts by status "
    "over a lookback window (default 7 days, max 90)."
)


def create_server() -> MCPServer:
    """Construct and wire the MCP server with tools + auth + health route."""
    server = MCPServer(
        name="ekoa-mcp-server",
        title="EKOA Knowledge MCP Server",
        version="0.1.0",
        description=(
            "EKOA tenancy-scoped knowledge access: search_knowledge_base "
            "retrieves relevant chunks from the workspace's vector index; "
            "list_documents enumerates indexed documents; get_workflow_status "
            "reports workflow run state; query_analytics summarizes AI usage "
            "and document stats. All require a valid MCP API key bound to a "
            "workspace."
        ),
        auth=AuthSettings(
            issuer_url=settings.MCP_ISSUER_URL,
            resource_server_url=settings.MCP_RESOURCE_SERVER_URL,
        ),
        token_verifier=EkoaTokenVerifier(),
    )

    @server.tool(name="search_knowledge_base", description=_SEARCH_DESCRIPTION)
    async def search_tool(query: str, limit: int = 5) -> dict:
        """Search the workspace knowledge base."""
        return await search_knowledge_base(query, limit)

    @server.tool(name="list_documents", description=_LIST_DESCRIPTION)
    async def documents_tool(cursor: str | None = None, limit: int = 20) -> dict:
        """List indexed documents in the workspace."""
        return await list_documents(cursor, limit)

    @server.tool(name="get_workflow_status", description=_WORKFLOW_STATUS_DESCRIPTION)
    async def workflow_status_tool() -> dict:
        """Report workspace workflow status."""
        return await get_workflow_status()

    @server.tool(name="query_analytics", description=_ANALYTICS_DESCRIPTION)
    async def analytics_tool(days: int = 7) -> dict:
        """Summarize workspace AI usage and document stats."""
        return await query_analytics(days)

    @server.custom_route("/health", methods=["GET"])
    async def health(request: Request) -> Response:
        """Liveness probe verifying real dependencies (DB + Qdrant)."""
        dependencies: dict[str, str] = {}
        try:
            async with get_mcp_session_factory()() as db:
                await db.execute(text("SELECT 1"))
            dependencies["database"] = "ok"
        except Exception as exc:  # noqa: BLE001
            dependencies["database"] = f"error: {type(exc).__name__}"

        try:
            from apps.ai.retriever import _get_qdrant

            _get_qdrant().get_collections()
            dependencies["qdrant"] = "ok"
        except Exception as exc:  # noqa: BLE001
            dependencies["qdrant"] = f"error: {type(exc).__name__}"

        healthy = all(v == "ok" for v in dependencies.values())
        return JSONResponse(
            {
                "status": "healthy" if healthy else "unhealthy",
                "service": "ekoa-mcp",
                "version": "0.1.0",
                "dependencies": dependencies,
                "tools": [
                    "search_knowledge_base",
                    "list_documents",
                    "get_workflow_status",
                    "query_analytics",
                ],
            },
            status_code=200 if healthy else 503,
        )

    return server


def run() -> None:
    """Run the MCP server over Streamable HTTP on the configured port."""
    server = create_server()
    server.run(
        transport="streamable-http",
        host=settings.MCP_HOST,
        port=settings.MCP_PORT,
        streamable_http_path=settings.MCP_STREAMABLE_HTTP_PATH,
    )


if __name__ == "__main__":
    run()