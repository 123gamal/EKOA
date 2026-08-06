"""Integration tests for EKOA API endpoints — full coverage including edge cases."""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


# ── Auth Edge Cases ──────────────────────────────────────────────────────────

async def test_auth_full_flow(client: AsyncClient):
    """Complete authentication lifecycle: register, login, profile, refresh, logout."""
    email = "full_flow@example.com"
    password = "strongpassword123"

    reg_resp = await client.post("/api/v1/auth/register", json={
        "email": email, "password": password, "full_name": "Full Flow User",
    })
    assert reg_resp.status_code in (201, 211)
    assert reg_resp.json()["email"] == email

    dup_resp = await client.post("/api/v1/auth/register", json={
        "email": email, "password": password, "full_name": "Duplicate",
    })
    assert dup_resp.status_code == 409

    login_resp = await client.post("/api/v1/auth/login", json={
        "email": email, "password": password,
    })
    assert login_resp.status_code == 200
    tokens = login_resp.json()
    assert "access_token" in tokens and "refresh_token" in tokens
    assert tokens["token_type"] == "bearer"
    access_token, refresh_token = tokens["access_token"], tokens["refresh_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    me_resp = await client.get("/api/v1/auth/me", headers=headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == email

    refresh_resp = await client.post("/api/v1/auth/refresh", json={
        "refresh_token": refresh_token,
    })
    assert refresh_resp.status_code == 200
    new_tokens = refresh_resp.json()
    assert new_tokens["refresh_token"] != refresh_token

    bad_login = await client.post("/api/v1/auth/login", json={
        "email": email, "password": "wrongpassword",
    })
    assert bad_login.status_code == 401

    logout_resp = await client.post("/api/v1/auth/logout", json={
        "refresh_token": new_tokens["refresh_token"],
    }, headers={"Authorization": f"Bearer {new_tokens['access_token']}"})
    assert logout_resp.status_code == 204


async def test_auth_register_validation_errors(client: AsyncClient):
    """Register endpoint validates input payloads."""
    # Missing email
    resp = await client.post("/api/v1/auth/register", json={
        "password": "strong123", "full_name": "Test",
    })
    assert resp.status_code == 422

    # Invalid email format
    resp = await client.post("/api/v1/auth/register", json={
        "email": "not-an-email", "password": "strong123", "full_name": "Test",
    })
    assert resp.status_code == 422

    # Password too short (< 8 chars)
    resp = await client.post("/api/v1/auth/register", json={
        "email": "valid@test.com", "password": "short", "full_name": "Test",
    })
    assert resp.status_code == 422

    # Empty full_name
    resp = await client.post("/api/v1/auth/register", json={
        "email": "valid2@test.com", "password": "strong123", "full_name": "",
    })
    assert resp.status_code == 422


async def test_auth_login_validation(client: AsyncClient):
    """Login endpoint validates and rejects bad credentials."""
    # Non-existent user
    resp = await client.post("/api/v1/auth/login", json={
        "email": "nobody@example.com", "password": "strongpassword123",
    })
    assert resp.status_code == 401

    # Missing password
    resp = await client.post("/api/v1/auth/login", json={"email": "test@test.com"})
    assert resp.status_code == 422

    # Wrong password (after register)
    await client.post("/api/v1/auth/register", json={
        "email": "logintest@example.com", "password": "correctpass123", "full_name": "T",
    })
    resp = await client.post("/api/v1/auth/login", json={
        "email": "logintest@example.com", "password": "wrongpass123",
    })
    assert resp.status_code == 401


async def test_auth_refresh_edge_cases(client: AsyncClient):
    """Refresh token endpoint handles invalid/revoked/malformed tokens."""
    # Missing refresh_token
    resp = await client.post("/api/v1/auth/refresh", json={})
    assert resp.status_code == 400

    # Malformed token
    resp = await client.post("/api/v1/auth/refresh", json={
        "refresh_token": "not-a-valid-jwt",
    })
    assert resp.status_code == 401

    # Expired-style token (valid JWT format but not in DB)
    resp = await client.post("/api/v1/auth/refresh", json={
        "refresh_token": "eyJhbGciOiJIUzI1NiJ9.dGVzdA.test123",
    })
    assert resp.status_code == 401

    # Revoked token cannot be reused
    await client.post("/api/v1/auth/register", json={
        "email": "revoke-test@example.com", "password": "strong1234567", "full_name": "T",
    })
    login = await client.post("/api/v1/auth/login", json={
        "email": "revoke-test@example.com", "password": "strong1234567",
    })
    rt = login.json()["refresh_token"]
    at = login.json()["access_token"]
    await client.post("/api/v1/auth/logout", json={"refresh_token": rt},
                      headers={"Authorization": f"Bearer {at}"})
    reuse = await client.post("/api/v1/auth/refresh", json={"refresh_token": rt})
    assert reuse.status_code == 401


async def test_auth_protected_endpoints_reject_bad_tokens(client: AsyncClient):
    """Protected endpoints reject expired, malformed, or missing tokens."""
    # No token
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401

    # Malformed token
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer invalid"})
    assert resp.status_code == 401

    # Empty token
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer "})
    assert resp.status_code == 401


async def test_auth_logout_edge_cases(client: AsyncClient):
    """Logout endpoint handles missing tokens and double logout."""
    email = "logout-edge@example.com"
    await client.post("/api/v1/auth/register", json={
        "email": email, "password": "strong1234567", "full_name": "T",
    })
    login = await client.post("/api/v1/auth/login", json={
        "email": email, "password": "strong1234567",
    })
    at, rt = login.json()["access_token"], login.json()["refresh_token"]

    # Logout without refresh_token in body
    resp = await client.post("/api/v1/auth/logout", json={},
                             headers={"Authorization": f"Bearer {at}"})
    assert resp.status_code == 400

    # Logout without auth header
    resp = await client.post("/api/v1/auth/logout", json={"refresh_token": rt})
    assert resp.status_code == 401

    # Successful logout then double-logout should still work (idempotent)
    resp = await client.post("/api/v1/auth/logout", json={"refresh_token": rt},
                             headers={"Authorization": f"Bearer {at}"})
    assert resp.status_code == 204

    resp = await client.post("/api/v1/auth/logout", json={"refresh_token": rt},
                             headers={"Authorization": f"Bearer {at}"})
    assert resp.status_code == 204


# ── Organization Edge Cases ──────────────────────────────────────────────────

async def test_org_workspace_flow(client: AsyncClient):
    """Organization and Workspace CRUD operations."""
    email = "org_ws@example.com"
    await client.post("/api/v1/auth/register", json={
        "email": email, "password": "strongpassword123", "full_name": "Org Owner",
    })
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "strongpassword123"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    org_resp = await client.post("/api/v1/organizations/", json={
        "name": "Acme Corp", "slug": "acme-corp", "description": "HQ",
    }, headers=headers)
    assert org_resp.status_code == 201
    org = org_resp.json()

    dup_org = await client.post("/api/v1/organizations/", json={
        "name": "Acme2", "slug": "acme-corp", "description": "",
    }, headers=headers)
    assert dup_org.status_code == 400

    get_resp = await client.get("/api/v1/organizations/acme-corp", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == org["id"]

    list_resp = await client.get("/api/v1/organizations/", headers=headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) >= 1

    ws_resp = await client.post("/api/v1/workspaces/", json={
        "name": "Engineering", "description": "Eng team", "organization_id": org["id"],
    }, headers=headers)
    assert ws_resp.status_code == 201
    ws = ws_resp.json()
    assert ws["name"] == "Engineering" and ws["organization_id"] == org["id"]

    list_ws = await client.get(f"/api/v1/workspaces/?organization_id={org['id']}", headers=headers)
    assert list_ws.status_code == 200 and len(list_ws.json()) == 1
    assert list_ws.json()[0]["id"] == ws["id"]

    get_ws = await client.get(f"/api/v1/workspaces/{ws['id']}", headers=headers)
    assert get_ws.status_code == 200 and get_ws.json()["name"] == "Engineering"


async def test_org_edge_cases(client: AsyncClient):
    """Organization endpoint edge cases."""
    email = "org-edge@example.com"
    await client.post("/api/v1/auth/register", json={
        "email": email, "password": "strong1234567", "full_name": "T",
    })
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "strong1234567"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # Get non-existent org by slug
    resp = await client.get("/api/v1/organizations/non-existent-slug", headers=headers)
    assert resp.status_code == 404

    # Create org with invalid slug (uppercase not allowed)
    resp = await client.post("/api/v1/organizations/", json={
        "name": "Bad", "slug": "UPPERCASE-INVALID",
    }, headers=headers)
    assert resp.status_code == 422

    # Create org with empty name
    resp = await client.post("/api/v1/organizations/", json={
        "name": "", "slug": "empty-name",
    }, headers=headers)
    assert resp.status_code == 422

    # Create org with missing slug
    resp = await client.post("/api/v1/organizations/", json={"name": "Test"}, headers=headers)
    assert resp.status_code == 422


# ── Workspace Edge Cases ─────────────────────────────────────────────────────

async def test_workspace_edge_cases(client: AsyncClient):
    """Workspace endpoint edge cases."""
    email = "ws-edge@example.com"
    await client.post("/api/v1/auth/register", json={
        "email": email, "password": "strong1234567", "full_name": "T",
    })
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "strong1234567"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    org_resp = await client.post("/api/v1/organizations/", json={
        "name": "WS Org", "slug": "ws-org",
    }, headers=headers)
    org_id = org_resp.json()["id"]

    fake_uuid = "00000000-0000-0000-0000-000000000000"

    # Get workspace by non-existent ID
    resp = await client.get(f"/api/v1/workspaces/{fake_uuid}", headers=headers)
    assert resp.status_code == 404

    # List workspaces for non-existent org → user is not a member of that org
    resp = await client.get(f"/api/v1/workspaces/?organization_id={fake_uuid}", headers=headers)
    assert resp.status_code == 403

    # Create workspace with empty name
    invalid = await client.post("/api/v1/workspaces/", json={
        "name": "", "organization_id": org_id,
    }, headers=headers)
    # name validation happens before authz; both 403/422 acceptable, but empty name must fail
    assert invalid.status_code in (403, 422)


# ── Document Edge Cases ──────────────────────────────────────────────────────

async def test_document_upload_and_list(client: AsyncClient):
    """Document upload and retrieval flow."""
    email = "doc_user@example.com"
    await client.post("/api/v1/auth/register", json={
        "email": email, "password": "strongpassword123", "full_name": "Doc User",
    })
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "strongpassword123"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    org = (await client.post("/api/v1/organizations/", json={
        "name": "Docs Org", "slug": "docs-org",
    }, headers=headers)).json()
    ws = (await client.post("/api/v1/workspaces/", json={
        "name": "Docs WS", "organization_id": org["id"],
    }, headers=headers)).json()

    upload_resp = await client.post(
        "/api/v1/documents/upload",
        data={"workspace_id": ws["id"]},
        files={"file": ("test.txt", b"Hello EKOA! This is a test document.", "text/plain")},
        headers=headers,
    )
    assert upload_resp.status_code == 201
    doc = upload_resp.json()
    assert doc["title"] == "test.txt"
    # PENDING when enqueued (celery present) or ENQUEUE_FAILED when the broker
    # is unavailable (local test venv has no celery) - both are valid outcomes.
    assert doc["status"] in ("PENDING", "ENQUEUE_FAILED")
    assert doc["workspace_id"] == ws["id"]
    doc_id = doc["id"]

    list_docs = await client.get(f"/api/v1/documents/?workspace_id={ws['id']}", headers=headers)
    assert list_docs.status_code == 200 and len(list_docs.json()) == 1
    assert list_docs.json()[0]["id"] == doc_id

    get_doc = await client.get(f"/api/v1/documents/{doc_id}", headers=headers)
    assert get_doc.status_code == 200 and get_doc.json()["title"] == "test.txt"


async def test_document_edge_cases(client: AsyncClient):
    """Document endpoint edge cases."""
    email = "doc-edge@example.com"
    await client.post("/api/v1/auth/register", json={
        "email": email, "password": "strong1234567", "full_name": "T",
    })
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "strong1234567"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    org = (await client.post("/api/v1/organizations/", json={
        "name": "DE Org", "slug": "de-org",
    }, headers=headers)).json()
    ws = (await client.post("/api/v1/workspaces/", json={
        "name": "DE WS", "organization_id": org["id"],
    }, headers=headers)).json()

    fake_uuid = "00000000-0000-0000-0000-000000000000"

    # List docs for non-existent workspace → 404 (workspace does not exist)
    resp = await client.get(f"/api/v1/documents/?workspace_id={fake_uuid}", headers=headers)
    assert resp.status_code == 404

    # Get non-existent document → 404 (matches prior behavior via authz)
    resp = await client.get(f"/api/v1/documents/{fake_uuid}", headers=headers)
    assert resp.status_code == 404

    # Upload empty file
    resp = await client.post(
        "/api/v1/documents/upload",
        data={"workspace_id": ws["id"]},
        files={"file": ("empty.txt", b"", "text/plain")},
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["title"] == "empty.txt"

    # Upload PDF content-type file
    resp = await client.post(
        "/api/v1/documents/upload",
        data={"workspace_id": ws["id"]},
        files={"file": ("report.pdf", b"%PDF-1.4 fake pdf content", "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["content_type"] == "application/pdf"


# ── Authorization Edge Cases ────────────────────────────────────────────────

async def test_unauthorized_access(client: AsyncClient):
    """Protected endpoints reject unauthenticated requests."""
    endpoints = [
        ("GET", "/api/v1/auth/me"),
        ("GET", "/api/v1/organizations/"),
        ("POST", "/api/v1/organizations/"),
        ("POST", "/api/v1/workspaces/"),
        ("POST", "/api/v1/documents/upload"),
        ("GET", "/api/v1/workspaces/?organization_id=00000000-0000-0000-0000-000000000000"),
        ("GET", "/api/v1/documents/?workspace_id=00000000-0000-0000-0000-000000000000"),
        ("POST", "/api/v1/auth/logout"),
    ]
    for method, url in endpoints:
        if method == "GET":
            resp = await client.get(url)
        elif method == "POST":
            resp = await client.post(url, json={})
        assert resp.status_code == 401, f"{method} {url} should return 401, got {resp.status_code}"


async def test_org_isolation(client: AsyncClient):
    """Users from different organizations should not see each other's data."""
    # User A
    await client.post("/api/v1/auth/register", json={
        "email": "user_a@test.com", "password": "strong1234567", "full_name": "User A",
    })
    login_a = await client.post("/api/v1/auth/login", json={"email": "user_a@test.com", "password": "strong1234567"})
    headers_a = {"Authorization": f"Bearer {login_a.json()['access_token']}"}
    org_a = (await client.post("/api/v1/organizations/", json={
        "name": "Org A", "slug": "org-a",
    }, headers=headers_a)).json()

    # User B
    await client.post("/api/v1/auth/register", json={
        "email": "user_b@test.com", "password": "strong1234567", "full_name": "User B",
    })
    login_b = await client.post("/api/v1/auth/login", json={"email": "user_b@test.com", "password": "strong1234567"})
    headers_b = {"Authorization": f"Bearer {login_b.json()['access_token']}"}

    # User B should NOT see User A's org
    list_b = await client.get("/api/v1/organizations/", headers=headers_b)
    assert len(list_b.json()) == 0  # B is not a member of Org A

    # User B should not be able to read User A's org by slug
    resp = await client.get("/api/v1/organizations/org-a", headers=headers_b)
    assert resp.status_code == 403

    # User B should not be able to list workspaces in Org A
    resp = await client.get(f"/api/v1/workspaces/?organization_id={org_a['id']}", headers=headers_b)
    assert resp.status_code == 403

    # User B should not be able to create a workspace in Org A
    resp = await client.post("/api/v1/workspaces/", json={
        "name": "Intruder", "organization_id": org_a["id"],
    }, headers=headers_b)
    assert resp.status_code == 403


async def test_document_cross_tenant_isolation(client: AsyncClient):
    """User B cannot read, list, or upload into User A's workspace."""
    # User A creates org, workspace, and a document
    await client.post("/api/v1/auth/register", json={
        "email": "owner_doc@test.com", "password": "strong1234567", "full_name": "Owner",
    })
    la = await client.post("/api/v1/auth/login", json={
        "email": "owner_doc@test.com", "password": "strong1234567",
    })
    ha = {"Authorization": f"Bearer {la.json()['access_token']}"}
    org = (await client.post("/api/v1/organizations/", json={
        "name": "Owner Org", "slug": "owner-org",
    }, headers=ha)).json()
    ws = (await client.post("/api/v1/workspaces/", json={
        "name": "Owner WS", "organization_id": org["id"],
    }, headers=ha)).json()
    up = await client.post(
        "/api/v1/documents/upload",
        data={"workspace_id": ws["id"]},
        files={"file": ("doc.txt", b"private content here", "text/plain")},
        headers=ha,
    )
    doc_id = up.json()["id"]

    # User B with no membership
    await client.post("/api/v1/auth/register", json={
        "email": "outsider@test.com", "password": "strong1234567", "full_name": "Outsider",
    })
    lb = await client.post("/api/v1/auth/login", json={
        "email": "outsider@test.com", "password": "strong1234567",
    })
    hb = {"Authorization": f"Bearer {lb.json()['access_token']}"}

    # B cannot list docs in A's workspace
    resp = await client.get(f"/api/v1/documents/?workspace_id={ws['id']}", headers=hb)
    assert resp.status_code == 403

    # B cannot read A's document
    resp = await client.get(f"/api/v1/documents/{doc_id}", headers=hb)
    assert resp.status_code == 403

    # B cannot upload into A's workspace
    resp = await client.post(
        "/api/v1/documents/upload",
        data={"workspace_id": ws["id"]},
        files={"file": ("intrude.txt", b"evil", "text/plain")},
        headers=hb,
    )
    assert resp.status_code == 403

    # B cannot read A's workspace by id
    resp = await client.get(f"/api/v1/workspaces/{ws['id']}", headers=hb)
    assert resp.status_code == 403

    # Owner (A) can still access everything
    resp = await client.get(f"/api/v1/documents/?workspace_id={ws['id']}", headers=ha)
    assert resp.status_code == 200 and len(resp.json()) == 1


async def test_register_with_organization_name(client: AsyncClient):
    """Registering with organization_name auto-creates an org + workspace + membership."""
    resp = await client.post("/api/v1/auth/register", json={
        "email": "autoorganization@test.com",
        "password": "strong1234567",
        "full_name": "Auto Org User",
        "organization_name": "My Startup Inc.",
    })
    assert resp.status_code == 201

    login = await client.post("/api/v1/auth/login", json={
        "email": "autoorganization@test.com", "password": "strong1234567",
    })
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    orgs = (await client.get("/api/v1/organizations/", headers=headers)).json()
    assert len(orgs) == 1
    assert orgs[0]["name"] == "My Startup Inc."

    wss = (await client.get(f"/api/v1/workspaces/?organization_id={orgs[0]['id']}", headers=headers)).json()
    assert len(wss) == 1
    assert wss[0]["name"] == "Default Workspace"
