"""E2E Live API Test Script for Enterprise Knowledge Operations Assistant (EKOA).

Tests all API endpoints using FastAPI TestClient with an in-memory SQLite DB.
"""
import sys
import os
import asyncio

# Set environment before importing settings or DB
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-e2e-testing-minimum-32-chars"
os.environ["TESTING"] = "1"

# Add paths
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, root)
sys.path.insert(0, os.path.join(root, "packages", "shared-config"))
sys.path.insert(0, os.path.join(root, "packages", "shared-types"))
sys.path.insert(0, os.path.join(root, "packages", "shared-utils"))
sys.path.insert(0, os.path.join(root, "apps", "api"))

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from apps.api.db.base import Base
from apps.api.main import app
from apps.api.db.engine import get_db

async def init_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    
    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    return engine

def run_e2e_tests():
    asyncio.run(init_db())
    client = TestClient(app)
    results = []

    print("\n=== STARTING END-TO-END REST API TEST SUITE ===")

    # 1. Health Check
    res = client.get("/health")
    assert res.status_code == 200, f"Health check failed: {res.text}"
    results.append("GET /health -> 200 OK")

    # 2. Root Check
    res = client.get("/")
    assert res.status_code == 200, f"Root check failed: {res.text}"
    results.append("GET / -> 200 OK")

    # 3. Auth - Register User 1
    reg_payload_1 = {
        "email": "testuser1@ekoa.io",
        "password": "Password123!",
        "full_name": "Test User One",
        "organization_name": "Acme Corp"
    }
    res = client.post("/api/v1/auth/register", json=reg_payload_1)
    assert res.status_code == 201, f"Register failed: {res.text}"
    user1_data = res.json()
    assert user1_data["email"] == "testuser1@ekoa.io"
    results.append("POST /api/v1/auth/register -> 201 Created")

    # 4. Auth - Duplicate Register check (Conflict 409)
    res = client.post("/api/v1/auth/register", json=reg_payload_1)
    assert res.status_code == 409, f"Duplicate register expected 409: {res.text}"
    results.append("POST /api/v1/auth/register (Duplicate Email) -> 409 Conflict")

    # 5. Auth - Login User 1
    login_payload = {
        "email": "testuser1@ekoa.io",
        "password": "Password123!"
    }
    res = client.post("/api/v1/auth/login", json=login_payload)
    assert res.status_code == 200, f"Login failed: {res.text}"
    login_data = res.json()
    token1 = login_data["access_token"]
    refresh1 = login_data["refresh_token"]
    results.append("POST /api/v1/auth/login -> 200 OK")

    # 6. Auth - Invalid Login check (401)
    bad_login = {"email": "testuser1@ekoa.io", "password": "WrongPassword!"}
    res = client.post("/api/v1/auth/login", json=bad_login)
    assert res.status_code == 401, f"Bad login expected 401: {res.text}"
    results.append("POST /api/v1/auth/login (Bad Password) -> 401 Unauthorized")

    # 7. Auth - Get Me Profile
    res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token1}"})
    assert res.status_code == 200, f"Me endpoint failed: {res.text}"
    assert res.json()["email"] == "testuser1@ekoa.io"
    results.append("GET /api/v1/auth/me -> 200 OK")

    # 8. Auth - Refresh Token
    res = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh1})
    assert res.status_code == 200, f"Refresh failed: {res.text}"
    token1 = res.json()["access_token"]
    results.append("POST /api/v1/auth/refresh -> 200 OK")

    # 9. Organizations - Create New Org
    new_org_payload = {
        "name": "Acme Corp",
        "slug": "acme-corp",
        "description": "Acme Corporation Knowledge Operations"
    }
    res = client.post("/api/v1/organizations/", json=new_org_payload, headers={"Authorization": f"Bearer {token1}"})
    assert res.status_code == 201, f"Create org failed: {res.text}"
    created_org = res.json()
    org_id = created_org["id"]
    org_slug = created_org["slug"]
    results.append("POST /api/v1/organizations/ -> 201 Created")

    # 10. Organizations - List User Orgs
    res = client.get("/api/v1/organizations/", headers={"Authorization": f"Bearer {token1}"})
    assert res.status_code == 200, f"List orgs failed: {res.text}"
    orgs = res.json()
    assert len(orgs) > 0
    results.append("GET /api/v1/organizations/ -> 200 OK")

    # 11. Organizations - Get by Slug
    res = client.get(f"/api/v1/organizations/{org_slug}", headers={"Authorization": f"Bearer {token1}"})
    assert res.status_code == 200, f"Get org by slug failed: {res.text}"
    results.append(f"GET /api/v1/organizations/{org_slug} -> 200 OK")

    # 12. Workspaces - Create Workspace
    ws_payload = {
        "name": "Engineering Knowledge",
        "description": "Engineering specs and docs",
        "organization_id": org_id
    }
    res = client.post("/api/v1/workspaces/", json=ws_payload, headers={"Authorization": f"Bearer {token1}"})
    assert res.status_code == 201, f"Create workspace failed: {res.text}"
    ws_data = res.json()
    ws_id = ws_data["id"]
    results.append("POST /api/v1/workspaces/ -> 201 Created")

    # 13. Workspaces - List Workspaces by Org
    res = client.get(f"/api/v1/workspaces/?organization_id={org_id}", headers={"Authorization": f"Bearer {token1}"})
    assert res.status_code == 200, f"List workspaces failed: {res.text}"
    results.append(f"GET /api/v1/workspaces/?organization_id={org_id} -> 200 OK")

    # 14. Workspaces - Get Workspace by ID
    res = client.get(f"/api/v1/workspaces/{ws_id}", headers={"Authorization": f"Bearer {token1}"})
    assert res.status_code == 200, f"Get workspace by id failed: {res.text}"
    results.append(f"GET /api/v1/workspaces/{ws_id} -> 200 OK")

    # 15. Documents - Upload Document
    dummy_file_content = b"Enterprise Knowledge Operations Assistant documentation content for testing ingestion."
    files = {"file": ("test_doc.txt", dummy_file_content, "text/plain")}
    data = {"workspace_id": ws_id, "title": "Test Spec Document"}
    res = client.post("/api/v1/documents/upload", data=data, files=files, headers={"Authorization": f"Bearer {token1}"})
    assert res.status_code == 201, f"Upload document failed: {res.text}"
    doc_data = res.json()
    doc_id = doc_data["id"]
    results.append("POST /api/v1/documents/upload -> 201 Created")

    # 16. Documents - List Documents in Workspace
    res = client.get(f"/api/v1/documents/?workspace_id={ws_id}", headers={"Authorization": f"Bearer {token1}"})
    assert res.status_code == 200, f"List documents failed: {res.text}"
    results.append(f"GET /api/v1/documents/?workspace_id={ws_id} -> 200 OK")

    # 17. Documents - Get Document by ID
    res = client.get(f"/api/v1/documents/{doc_id}", headers={"Authorization": f"Bearer {token1}"})
    assert res.status_code == 200, f"Get document failed: {res.text}"
    results.append(f"GET /api/v1/documents/{doc_id} -> 200 OK")

    # 18. Auth - Logout
    res = client.post("/api/v1/auth/logout", json={"refresh_token": refresh1}, headers={"Authorization": f"Bearer {token1}"})
    assert res.status_code == 204, f"Logout failed: {res.text}"
    results.append("POST /api/v1/auth/logout -> 204 No Content")

    print("\n=== SUMMARY OF ALL TESTED REST API ENDPOINTS ===")
    for r in results:
        print(f"  [OK] {r}")

    print(f"\nALL {len(results)} API ENDPOINT FLOWS EXECUTED SUCCESSFULLY WITHOUT ERRORS!\n")

if __name__ == "__main__":
    run_e2e_tests()
