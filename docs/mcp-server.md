# EKOA MCP Server

The EKOA MCP server exposes the knowledge base over the Model Context Protocol so
MCP clients (IDE assistants, Claude Desktop, custom agents) can search and list
the content you have indexed in a workspace.

- **Transport:** Streamable HTTP at `http://localhost:8002/mcp` (the 2025-03-26
  protocol-revision successor to SSE; no new servers should be built on SSE).
- **Auth:** every MCP request must present an MCP API key as a Bearer token
  (`Authorization: Bearer <key>`). The server answers `401 Unauthorized` for
  missing, unknown, or revoked keys.
- **Scope:** all tools are tenant-scoped. Your key is bound to exactly one
  workspace; searches and listings are pinned to that workspace's data.

## Tools

| Tool | Description |
| --- | --- |
| `search_knowledge_base(query, limit=5)` | Returns the top relevant chunks from the workspace's vector index (Phase 4 retriever) with similarity scores, scoped to the owning organization + workspace. |
| `list_documents(cursor=None, limit=20)` | Lists indexed document metadata (`id`, `title`, `status`, `source`, `chunk_count`, …) with cursor-based pagination via `next_cursor`. |

Every tool call is written to the audit log (`mcp.tool_call`) and bumps the key's
`last_used_at`.

## Managing API keys

Create/list/revoke keys through the REST API (`/api/v1/mcp/*`). These endpoints
are **admin/owner-gated** and audited.

```bash
# Authenticate (returns a JWT in access_token)
TOKEN=$(curl -s http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"..."}' | jq -r .access_token)

# Create a key for a workspace (plaintext shown exactly once)
curl -s http://localhost:8000/api/v1/mcp/keys/ \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name":"claude-desktop","workspace_id":"<workspace_id>"}'
# → { "key": "ekoa_<org8>_<ws8>_<96hex>", ... }   ← save this now

# List keys (only prefix + lifecycle metadata; never the plaintext)
curl -s "http://localhost:8000/api/v1/mcp/keys/?workspace_id=<workspace_id>" \
  -H "Authorization: Bearer $TOKEN"

# Revoke a key (effective immediately — the MCP server rejects it on next use)
curl -s -X POST http://localhost:8000/api/v1/mcp/keys/<key_id>/revoke \
  -H "Authorization: Bearer $TOKEN"
```

**Storage model:** only the SHA-256 hash of the key and a short identifying prefix
are stored. The raw key is high-entropy and shown once at creation; it cannot be
recovered or re-listed later.

## Connecting a client

Any MCP client that supports Streamable HTTP can connect with basic auth:

### Claude Desktop (streamable HTTP via a proxy/CLI MCP server)

```json
{
  "mcpServers": {
    "ekoa": {
      "url": "http://localhost:8002/mcp",
      "headers": { "Authorization": "Bearer ekoa_<key>" }
    }
  }
}
```

### Python SDK client

```python
import asyncio
from mcp import Client
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

async def main():
    http = create_mcp_http_client(headers={"Authorization": "Bearer <key>"})
    async with Client(streamable_http_client("http://localhost:8002/mcp", http_client=http)) as mcp:
        tools = await mcp.list_tools()
        print([t.name for t in tools])  # search_knowledge_base, list_documents

        result = await mcp.call_tool("search_knowledge_base", {"query": "SSL certificate trust", "limit": 3})
        print(result)

asyncio.run(main())
```

## Health

`GET http://localhost:8002/health` (auth-exempt) returns `200` only when the
database and Qdrant are reachable, so the Docker healthcheck fails for a truly
degraded service:

```bash
curl -s http://localhost:8002/health
# {"status":"healthy","service":"ekoa-mcp","version":"0.1.0",...}
```

## Running it

```bash
docker compose -f infrastructure/docker/docker-compose.yml up --build -d mcp
```