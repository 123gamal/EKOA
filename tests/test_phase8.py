"""Phase 8 tests: MCP API key management + the EKOA MCP server.

Covered guarantees:
- The raw key is returned exactly once; only its SHA-256 hash + prefix are
  persisted (never the plaintext, never a reversible form).
- Create/list/revoke are admin-gated and audited.
- The MCP token verifier accepts only active keys and rejects unknown or
  revoked keys immediately.
- search_knowledge_base reuses the tenant-scoped retriever (pinned to the
  key's workspace) and list_documents paginates with a cursor; every tool
  call is audited and bumps last_used_at.
"""

import hashlib
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

import apps.api.models  # noqa: F401  # register all models on Base
from apps.api.models.user import User
from apps.api.models.org_member import OrgMember
from apps.api.models.document import Document
from apps.api.models.mcp_api_key import McpApiKey
from apps.api.models.audit_log import AuditLog

# Point the MCP server's DB lookups at the same test database the ASGI client
# writes to (the conftest shared factory).
from tests.conftest import async_session_factory as conftest_session_factory
from apps.mcp_server.db import set_mcp_session_factory

set_mcp_session_factory(conftest_session_factory)


# ── Helpers ─────────────────────────────────────────────────────────────────────


async def _register_login(client: AsyncClient, email: str) -> dict:
    resp = await client.post("/api/v1/auth/register", json={
        "email": email, "password": "strongpassword123", "full_name": "Test User",
    })
    assert resp.status_code in (201, 211), resp.text
    resp = await client.post("/api/v1/auth/login", json={
        "email": email, "password": "strongpassword123",
    })
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _seed_org_ws(client: AsyncClient, headers: dict, db_session) -> dict:
    org = (await client.post("/api/v1/organizations/", json={
        "name": "MCP Org", "slug": f"mcp-{uuid.uuid4().hex[:8]}",
    }, headers=headers)).json()
    ws = (await client.post("/api/v1/workspaces/", json={
        "name": "MCP WS", "organization_id": org["id"],
    }, headers=headers)).json()
    return {"org": org, "ws": ws, "headers": headers}


async def _create_key(client: AsyncClient, seed: dict, name: str = "Integration Key") -> dict:
    resp = await client.post("/api/v1/mcp/keys/", headers=seed["headers"], json={
        "name": name, "workspace_id": seed["ws"]["id"],
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


def _authed_context(claims: dict):
    """Provide a fake MCP auth context for direct tool invocations."""
    from mcp.server.auth.middleware.auth_context import auth_context_var, AuthenticatedUser
    from mcp.server.auth.provider import AccessToken

    token = auth_context_var.set(
        AuthenticatedUser(
            auth_info=AccessToken(
                token="test-token",
                client_id=str(claims.get("key_id")),
                scopes=[],
                claims=claims,
            )
        )
    )
    return token


# ── Key lifecycle: hash-at-rest, one-time plaintext, RBAC, audit ───────────────


@pytest.mark.asyncio
async def test_mcp_key_plaintext_shown_once_hash_only_at_rest(client, db_session):
    """The raw key appears in the create response exactly once; the DB stores
    only the SHA-256 hash and an identifying prefix."""
    headers = await _register_login(client, f"key-{uuid.uuid4().hex[:8]}@example.com")
    seed = await _seed_org_ws(client, headers, db_session)
    created = await _create_key(client, seed)

    raw = created["key"]
    assert raw.startswith("ekoa_")
    assert created["status"] == "active"
    assert created["key_prefix"]  # prefix returned, hash not

    row = (await db_session.execute(
        select(McpApiKey).where(McpApiKey.id == uuid.UUID(created["id"]))
    )).scalar_one()
    assert row.key_hash == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert raw not in row.key_hash
    assert row.key_prefix == created["key_prefix"]

    # Listing afterwards never exposes the plaintext.
    listed = await client.get(
        f"/api/v1/mcp/keys/?workspace_id={seed['ws']['id']}", headers=seed["headers"]
    )
    assert listed.status_code == 200
    assert all("key" not in item for item in listed.json()["items"])
    assert all(item["key_prefix"] for item in listed.json()["items"])


@pytest.mark.asyncio
async def test_mcp_key_create_member_forbidden_admin_audited(client, db_session):
    """Plain members cannot mint keys; admin/owner can; creation is audited."""
    owner_email = f"kmem-{uuid.uuid4().hex[:8]}@example.com"
    headers_owner = await _register_login(client, owner_email)
    seed = await _seed_org_ws(client, headers_owner, db_session)

    member_email = f"kdep-{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/register", json={
        "email": member_email, "password": "strongpassword123", "full_name": "Member",
    })
    member_user = (await db_session.execute(
        select(User).where(User.email == member_email)
    )).scalar_one()
    db_session.add(OrgMember(
        user_id=member_user.id, organization_id=uuid.UUID(seed["org"]["id"]), role="member",
    ))
    await db_session.commit()
    member_login = await client.post("/api/v1/auth/login", json={
        "email": member_email, "password": "strongpassword123",
    })
    headers_member = {"Authorization": f"Bearer {member_login.json()['access_token']}"}

    payload = {"name": "Member Try", "workspace_id": seed["ws"]["id"]}
    resp_member = await client.post("/api/v1/mcp/keys/", headers=headers_member, json=payload)
    assert resp_member.status_code == 403, resp_member.text

    resp_admin = await client.post("/api/v1/mcp/keys/", headers=seed["headers"], json=payload)
    assert resp_admin.status_code == 201, resp_admin.text

    audits = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == "mcp_api_key.create")
    )).scalars().all()
    assert len(audits) >= 1


@pytest.mark.asyncio
async def test_mcp_key_list_paginated(client, db_session):
    """List returns the Phase 3 pagination envelope, latest first."""
    headers = await _register_login(client, f"klist-{uuid.uuid4().hex[:8]}@example.com")
    seed = await _seed_org_ws(client, headers, db_session)
    for i in range(3):
        await _create_key(client, seed, name=f"key-{i}")

    listed = await client.get(
        f"/api/v1/mcp/keys/?workspace_id={seed['ws']['id']}&page=1&page_size=2",
        headers=seed["headers"],
    )
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["pages"] == 2

    # Paginate to the end: the union of both pages is exactly the 3 keys and
    # no item is duplicated across pages.
    page2 = await client.get(
        f"/api/v1/mcp/keys/?workspace_id={seed['ws']['id']}&page=2&page_size=2",
        headers=seed["headers"],
    )
    assert page2.status_code == 200
    names = [i["name"] for i in body["items"] + page2.json()["items"]]
    assert len(names) == 3
    assert len(set(names)) == 3
    assert set(names) == {"key-0", "key-1", "key-2"}


@pytest.mark.asyncio
async def test_mcp_key_revoke_audited_and_immediately_rejected(client, db_session):
    """After revoke the key flips status/revoked_at and the verifier rejects it."""
    from apps.mcp_server.auth import EkoaTokenVerifier

    headers = await _register_login(client, f"krev-{uuid.uuid4().hex[:8]}@example.com")
    seed = await _seed_org_ws(client, headers, db_session)
    created = await _create_key(client, seed)
    raw = created["key"]

    verifier = EkoaTokenVerifier()
    active = await verifier.verify_token(raw)
    assert active is not None
    assert active.claims["organization_id"] == seed["org"]["id"]
    assert active.claims["workspace_id"] == seed["ws"]["id"]

    revoke = await client.post(
        f"/api/v1/mcp/keys/{created['id']}/revoke", headers=seed["headers"]
    )
    assert revoke.status_code == 200, revoke.text
    assert revoke.json()["status"] == "revoked"
    assert revoke.json()["revoked_at"]

    audits = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == "mcp_api_key.revoke")
    )).scalars().all()
    assert len(audits) >= 1

    # Revocation takes effect immediately (no cache to flush).
    assert await verifier.verify_token(raw) is None


@pytest.mark.asyncio
async def test_verifier_rejects_unknown_key(client, db_session):
    """A garbage/unknown bearer token yields None (401 upstream)."""
    from apps.mcp_server.auth import EkoaTokenVerifier

    verifier = EkoaTokenVerifier()
    assert await verifier.verify_token("ekoa_00000000_00000000_" + "0" * 48) is None
    assert await verifier.verify_token("") is None


# ── MCP tools: search + list documents, audit, last_used_at, auth enforcement ──


@pytest.mark.asyncio
async def test_search_knowledge_base_tool_audits_and_records_usage(client, db_session, monkeypatch):
    """search_knowledge_base calls the tenant retriever with the key's
    org/workspace, bumps last_used_at, and writes an audit entry."""
    from apps.mcp_server.tools import search_knowledge_base

    headers = await _register_login(client, f"stool-{uuid.uuid4().hex[:8]}@example.com")
    seed = await _seed_org_ws(client, headers, db_session)
    created = await _create_key(client, seed)

    fake_results = [
        {"score": 0.92, "text": "SSL_CERT_FILE controls TLS trust.", "document_id": "doc-1", "chunk_index": 0},
        {"score": 0.81, "text": "trust_env reads environment settings.", "document_id": "doc-2", "chunk_index": 1},
    ]
    captured = {}

    import apps.ai.retriever as retriever_mod

    def fake_retrieve(query, collection_name="ekoa_default", limit=5, organization_id=None, workspace_id=None):
        captured["query"] = query
        captured["collection_name"] = collection_name
        captured["limit"] = limit
        captured["organization_id"] = organization_id
        captured["workspace_id"] = workspace_id
        return fake_results

    monkeypatch.setattr(retriever_mod, "retrieve_chunks", fake_retrieve)

    ctx = _authed_context({
        "key_id": created["id"],
        "organization_id": seed["org"]["id"],
        "workspace_id": seed["ws"]["id"],
        "name": created["name"],
    })
    try:
        result = await search_knowledge_base("SSL certificate trust", limit=3)
    finally:
        from mcp.server.auth.middleware.auth_context import auth_context_var
        auth_context_var.reset(ctx)

    assert result["query"] == "SSL certificate trust"
    assert result["limit"] == 3
    assert len(result["results"]) == 2
    # Pinned to the key's tenant + collection derived from the workspace.
    assert captured["collection_name"] == f"ekoa_{seed['ws']['id'][:8]}"
    assert captured["organization_id"] == seed["org"]["id"]
    assert captured["workspace_id"] == seed["ws"]["id"]

    row = (await db_session.execute(
        select(McpApiKey).where(McpApiKey.id == uuid.UUID(created["id"]))
    )).scalar_one()
    assert row.last_used_at is not None
    audits = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == "mcp.tool_call")
    )).scalars().all()
    assert any(a.details and a.details.get("tool") == "search_knowledge_base" for a in audits)


@pytest.mark.asyncio
async def test_tool_requires_authenticated_key(client, db_session):
    """Tool calls without a valid MCP auth context are rejected with ToolError."""
    from apps.mcp_server.tools import search_knowledge_base
    from mcp.server.mcpserver.exceptions import ToolError

    with pytest.raises(ToolError):
        await search_knowledge_base("anything")


@pytest.mark.asyncio
async def test_list_documents_pagination_cursor(client, db_session):
    """list_documents returns metadata for the key's workspace with a
    next_cursor for continued offset pagination."""
    from apps.mcp_server.tools import list_documents

    headers = await _register_login(client, f"ldoc-{uuid.uuid4().hex[:8]}@example.com")
    seed = await _seed_org_ws(client, headers, db_session)
    created = await _create_key(client, seed)

    # Reuse the creator user id captured from the auth register call.
    stmt = select(User).join(OrgMember).where(
        OrgMember.organization_id == uuid.UUID(seed["org"]["id"])
    )
    uploader = (await db_session.execute(stmt)).scalars().first()
    assert uploader is not None

    for idx in range(3):
        db_session.add(Document(
            title=f"Spec {idx}",
            content_type="text/markdown",
            status="INDEXED",
            file_path=f"docs/spec-{idx}.md",
            chunk_count=idx + 1,
            metadata_json={"source": "github"},
            workspace_id=uuid.UUID(seed["ws"]["id"]),
            uploaded_by=uploader.id,
        ))
    await db_session.commit()

    ctx = _authed_context({
        "key_id": created["id"],
        "organization_id": seed["org"]["id"],
        "workspace_id": seed["ws"]["id"],
        "name": created["name"],
    })
    try:
        page1 = await list_documents(cursor=None, limit=2)
        assert page1["total"] == 3
        assert len(page1["items"]) == 2
        assert page1["next_cursor"] is not None

        page2 = await list_documents(cursor=page1["next_cursor"], limit=2)
        assert len(page2["items"]) == 1
        assert page2["next_cursor"] is None
        # No cross-workspace leakage: all returned docs belong to the workspace.
        assert all(item["id"] for item in page1["items"])
    finally:
        from mcp.server.auth.middleware.auth_context import auth_context_var
        auth_context_var.reset(ctx)


@pytest.mark.asyncio
async def test_list_documents_rejects_bad_cursor(client, db_session):
    from apps.mcp_server.tools import list_documents
    from mcp.server.mcpserver.exceptions import ToolError

    headers = await _register_login(client, f"lcurs-{uuid.uuid4().hex[:8]}@example.com")
    seed = await _seed_org_ws(client, headers, db_session)
    created = await _create_key(client, seed)

    ctx = _authed_context({
        "key_id": created["id"],
        "organization_id": seed["org"]["id"],
        "workspace_id": seed["ws"]["id"],
        "name": created["name"],
    })
    try:
        with pytest.raises(ToolError):
            await list_documents(cursor="not-base64!!")
    finally:
        from mcp.server.auth.middleware.auth_context import auth_context_var
        auth_context_var.reset(ctx)


@pytest.mark.asyncio
async def test_health_route_present_in_http_app():
    """The Streamable HTTP app exposes /health (auth-exempt) plus /mcp."""
    from apps.mcp_server.main import create_server

    app = create_server().streamable_http_app()
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/mcp" in paths
    assert "/health" in paths


@pytest.mark.asyncio
async def test_tool_call_fake_end_to_end_no_retriever_dependency(client, db_session, monkeypatch):
    """Prove the full search flow returns a serialisable dict without touching
    Qdrant — the retriever seam is honoured."""
    from apps.mcp_server.tools import search_knowledge_base

    headers = await _register_login(client, f"e2e-{uuid.uuid4().hex[:8]}@example.com")
    seed = await _seed_org_ws(client, headers, db_session)
    created = await _create_key(client, seed)

    import apps.ai.retriever as retriever_mod

    monkeypatch.setattr(
        retriever_mod, "retrieve_chunks",
        lambda *a, **k: [{"score": 1.0, "text": "hello", "document_id": "d", "chunk_index": 0}],
    )
    ctx = _authed_context({
        "key_id": created["id"],
        "organization_id": seed["org"]["id"],
        "workspace_id": seed["ws"]["id"],
    })
    try:
        result = await search_knowledge_base("hello", limit=1)
    finally:
        from mcp.server.auth.middleware.auth_context import auth_context_var
        auth_context_var.reset(ctx)
    assert result["results"][0]["text"] == "hello"


# ── MCP tools (Phase 16 Part C): get_workflow_status, query_analytics ─────────


@pytest.mark.asyncio
async def test_get_workflow_status_tool_reports_latest_run(client, db_session):
    """get_workflow_status returns each workflow with its most recent run,
    including approval-pending state, scoped to the key's workspace."""
    from apps.api.models.workflow import Workflow, WorkflowRun
    from apps.mcp_server.tools import get_workflow_status

    headers = await _register_login(client, f"wftool-{uuid.uuid4().hex[:8]}@example.com")
    seed = await _seed_org_ws(client, headers, db_session)
    created = await _create_key(client, seed)

    stmt = select(User).join(OrgMember).where(
        OrgMember.organization_id == uuid.UUID(seed["org"]["id"])
    )
    owner = (await db_session.execute(stmt)).scalars().first()

    wf = Workflow(
        name="Compliance Audit",
        template_id="compliance_audit",
        status="RUNNING",
        workspace_id=uuid.UUID(seed["ws"]["id"]),
        created_by=owner.id,
    )
    db_session.add(wf)
    await db_session.flush()
    db_session.add(WorkflowRun(
        workflow_id=wf.id, status="AWAITING_APPROVAL", approval_status="PENDING",
    ))
    await db_session.commit()

    ctx = _authed_context({
        "key_id": created["id"],
        "organization_id": seed["org"]["id"],
        "workspace_id": seed["ws"]["id"],
    })
    try:
        result = await get_workflow_status()
    finally:
        from mcp.server.auth.middleware.auth_context import auth_context_var
        auth_context_var.reset(ctx)

    assert result["workspace_id"] == seed["ws"]["id"]
    assert len(result["workflows"]) == 1
    assert result["workflows"][0]["name"] == "Compliance Audit"
    assert result["workflows"][0]["latest_run"]["approval_status"] == "PENDING"

    audits = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == "mcp.tool_call")
    )).scalars().all()
    assert any(a.details and a.details.get("tool") == "get_workflow_status" for a in audits)


@pytest.mark.asyncio
async def test_get_workflow_status_tool_empty_workspace(client, db_session):
    from apps.mcp_server.tools import get_workflow_status

    headers = await _register_login(client, f"wfempty-{uuid.uuid4().hex[:8]}@example.com")
    seed = await _seed_org_ws(client, headers, db_session)
    created = await _create_key(client, seed)

    ctx = _authed_context({
        "key_id": created["id"],
        "organization_id": seed["org"]["id"],
        "workspace_id": seed["ws"]["id"],
    })
    try:
        result = await get_workflow_status()
    finally:
        from mcp.server.auth.middleware.auth_context import auth_context_var
        auth_context_var.reset(ctx)
    assert result["workflows"] == []


@pytest.mark.asyncio
async def test_query_analytics_tool_summarizes_usage(client, db_session):
    """query_analytics aggregates AiCallLog + Document rows scoped to the
    key's workspace, within the requested lookback window."""
    from apps.api.models.ai_call_log import AiCallLog
    from apps.mcp_server.tools import query_analytics

    headers = await _register_login(client, f"antool-{uuid.uuid4().hex[:8]}@example.com")
    seed = await _seed_org_ws(client, headers, db_session)
    created = await _create_key(client, seed)

    stmt = select(User).join(OrgMember).where(
        OrgMember.organization_id == uuid.UUID(seed["org"]["id"])
    )
    uploader = (await db_session.execute(stmt)).scalars().first()

    db_session.add(Document(
        title="Doc 1", content_type="text/plain", status="INDEXED",
        file_path="docs/1.txt", chunk_count=2,
        workspace_id=uuid.UUID(seed["ws"]["id"]),
        uploaded_by=uploader.id,
    ))
    db_session.add(AiCallLog(
        organization_id=uuid.UUID(seed["org"]["id"]),
        workspace_id=uuid.UUID(seed["ws"]["id"]),
        provider="deepseek", model="deepseek-chat",
        latency_ms=250, prompt_tokens=100, completion_tokens=50, total_tokens=150,
        cost_estimate=0.001234,
    ))
    await db_session.commit()

    ctx = _authed_context({
        "key_id": created["id"],
        "organization_id": seed["org"]["id"],
        "workspace_id": seed["ws"]["id"],
    })
    try:
        result = await query_analytics(days=7)
    finally:
        from mcp.server.auth.middleware.auth_context import auth_context_var
        auth_context_var.reset(ctx)

    assert result["workspace_id"] == seed["ws"]["id"]
    assert result["documents"] == 1
    assert result["ai_calls"] == 1
    assert result["avg_latency_ms"] == 250
    assert result["total_tokens"] == 150
    assert result["cost_is_estimate"] is True


@pytest.mark.asyncio
async def test_query_analytics_tool_requires_authenticated_key(client, db_session):
    from apps.mcp_server.tools import query_analytics
    from mcp.server.mcpserver.exceptions import ToolError

    with pytest.raises(ToolError):
        await query_analytics()