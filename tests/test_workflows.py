"""Integration tests for the Workflow and Analytics endpoints."""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _user_with_workspace(client: AsyncClient, email: str):
    """Helper: register a user, create an org + workspace, return auth headers and workspace."""
    await client.post("/api/v1/auth/register", json={
        "email": email, "password": "strong1234567", "full_name": "T",
    })
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "strong1234567"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    org = (await client.post("/api/v1/organizations/", json={
        "name": f"Org {email}", "slug": f"org-{email.split('@')[0]}",
    }, headers=headers)).json()
    ws = (await client.post("/api/v1/workspaces/", json={
        "name": "Default Workspace", "organization_id": org["id"],
    }, headers=headers)).json()
    return headers, ws, org


# ── Workflow Templates ───────────────────────────────────────────────────────

async def test_workflow_templates_require_auth(client: AsyncClient):
    """Template catalog is protected."""
    resp = await client.get("/api/v1/workflows/templates")
    assert resp.status_code == 401


async def test_workflow_templates_list(client: AsyncClient):
    """The template catalog exposes the three real automation templates."""
    headers, _, _ = await _user_with_workspace(client, "tmpl@example.com")
    resp = await client.get("/api/v1/workflows/templates", headers=headers)
    assert resp.status_code == 200
    templates = resp.json()
    assert len(templates) >= 3
    ids = {t["id"] for t in templates}
    assert {"doc-ingest-rag", "compliance-audit", "support-router"} <= ids
    for t in templates:
        assert t["title"] and t["description"] and t["category"]
        assert len(t["steps"]) >= 2


# ── Workflow CRUD ────────────────────────────────────────────────────────────

async def test_workflow_crud(client: AsyncClient):
    """Create, list, and fetch workflow instances."""
    headers, ws, _ = await _user_with_workspace(client, "wfcrud@example.com")

    # Create
    resp = await client.post("/api/v1/workflows/", json={
        "name": "RAG Pipeline",
        "description": "Index everything",
        "template_id": "doc-ingest-rag",
        "workspace_id": ws["id"],
    }, headers=headers)
    assert resp.status_code == 201
    wf = resp.json()
    assert wf["name"] == "RAG Pipeline"
    assert wf["template_id"] == "doc-ingest-rag"
    assert wf["status"] == "DRAFT"
    assert wf["workspace_id"] == ws["id"]

    # Unknown template rejected
    resp = await client.post("/api/v1/workflows/", json={
        "name": "Bad", "template_id": "does-not-exist", "workspace_id": ws["id"],
    }, headers=headers)
    assert resp.status_code == 400

    # List
    resp = await client.get(f"/api/v1/workflows/?workspace_id={ws['id']}", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["id"] == wf["id"]

    # Get
    resp = await client.get(f"/api/v1/workflows/{wf['id']}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "RAG Pipeline"


async def test_workflow_cross_tenant_isolation(client: AsyncClient):
    """User B cannot see or run User A's workflows."""
    headers_a, ws_a, _ = await _user_with_workspace(client, "wfowner@example.com")
    headers_b, _, _ = await _user_with_workspace(client, "wfoutsider@example.com")

    wf = (await client.post("/api/v1/workflows/", json={
        "name": "Private", "template_id": "compliance-audit", "workspace_id": ws_a["id"],
    }, headers=headers_a)).json()

    # B cannot list A's workflows
    resp = await client.get(f"/api/v1/workflows/?workspace_id={ws_a['id']}", headers=headers_b)
    assert resp.status_code == 403

    # B cannot get A's workflow
    resp = await client.get(f"/api/v1/workflows/{wf['id']}", headers=headers_b)
    assert resp.status_code == 403

    # B cannot create a workflow in A's workspace
    resp = await client.post("/api/v1/workflows/", json={
        "name": "Intruder", "template_id": "doc-ingest-rag", "workspace_id": ws_a["id"],
    }, headers=headers_b)
    assert resp.status_code == 403


# ── Workflow Run ─────────────────────────────────────────────────────────────

async def test_workflow_run_creates_run_record(client: AsyncClient):
    """Triggering a run returns a WorkflowRun and persists it to history."""
    headers, ws, _ = await _user_with_workspace(client, "wfrun@example.com")
    wf = (await client.post("/api/v1/workflows/", json={
        "name": "Compliance", "template_id": "compliance-audit", "workspace_id": ws["id"],
    }, headers=headers)).json()

    resp = await client.post(f"/api/v1/workflows/{wf['id']}/run", json={}, headers=headers)
    assert resp.status_code == 201
    run = resp.json()
    assert run["workflow_id"] == wf["id"]
    # Without a live Celery worker the run is marked PENDING (enqueued) or
    # FAILED (worker unreachable) — both are valid outcomes of the contract.
    assert run["status"] in ("PENDING", "FAILED")
    if run["status"] == "FAILED":
        assert run["error"]

    # The workflow status is no longer DRAFT
    wf_after = (await client.get(f"/api/v1/workflows/{wf['id']}", headers=headers)).json()
    assert wf_after["status"] in ("PENDING", "FAILED")

    # Runs are recorded in history
    runs = (await client.get(f"/api/v1/workflows/{wf['id']}/runs", headers=headers)).json()
    assert len(runs) == 1
    assert runs[0]["id"] == run["id"]


async def test_workflow_run_auth(client: AsyncClient):
    """Run trigger requires workspace membership."""
    headers_a, ws_a, _ = await _user_with_workspace(client, "runauth@example.com")
    headers_b, _, _ = await _user_with_workspace(client, "runb@example.com")
    wf = (await client.post("/api/v1/workflows/", json={
        "name": "Support", "template_id": "support-router", "workspace_id": ws_a["id"],
    }, headers=headers_a)).json()

    resp = await client.post(f"/api/v1/workflows/{wf['id']}/run", json={}, headers=headers_b)
    assert resp.status_code == 403

    resp = await client.get(f"/api/v1/workflows/{wf['id']}/runs", headers=headers_b)
    assert resp.status_code == 403


# ── Analytics ────────────────────────────────────────────────────────────────

async def test_analytics_requires_auth(client: AsyncClient):
    """Analytics endpoints are protected."""
    resp = await client.get("/api/v1/analytics/overview")
    assert resp.status_code == 401


async def test_analytics_overview_reflects_real_data(client: AsyncClient):
    """Analytics overview reports live DB-derived counts scoped to the user."""
    headers, ws, org = await _user_with_workspace(client, "analytics@example.com")

    # Upload a document and create a workflow + run to populate real data
    up = await client.post(
        "/api/v1/documents/upload",
        data={"workspace_id": ws["id"]},
        files={"file": ("data.txt", b"Hello EKOA analytics payload.", "text/plain")},
        headers=headers,
    )
    assert up.status_code == 201

    wf = (await client.post("/api/v1/workflows/", json={
        "name": "Ingest", "template_id": "doc-ingest-rag", "workspace_id": ws["id"],
    }, headers=headers)).json()
    await client.post(f"/api/v1/workflows/{wf['id']}/run", json={}, headers=headers)

    resp = await client.get("/api/v1/analytics/overview", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["organizations"] >= 1
    assert data["workspaces"] >= 1
    assert data["documents"] >= 1
    # The upload is either enqueued (celery installed) or visibly failed to
    # enqueue (test venv has no celery) - both are reflected in the status map.
    assert (
        data["documents_by_status"].get("PENDING", 0)
        + data["documents_by_status"].get("ENQUEUE_FAILED", 0)
    ) >= 1
    assert data["chunks"] >= 0
    assert "uploads_last_7_days" in data
    assert len(data["recent_runs"]) >= 1
    assert any(a["action"] == "workflow.run" for a in data["recent_activity"])


async def test_analytics_documents(client: AsyncClient):
    """Analytics documents endpoint lists the user's documents with workspace names."""
    headers, ws, _ = await _user_with_workspace(client, "analyticsdocs@example.com")
    await client.post(
        "/api/v1/documents/upload",
        data={"workspace_id": ws["id"]},
        files={"file": ("guide.md", b"# Guide", "text/markdown")},
        headers=headers,
    )

    resp = await client.get("/api/v1/analytics/documents", headers=headers)
    assert resp.status_code == 200
    docs = resp.json()["documents"]
    assert len(docs) == 1
    assert docs[0]["title"] == "guide.md"
    assert docs[0]["workspace"] == "Default Workspace"
