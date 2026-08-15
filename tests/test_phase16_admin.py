"""Phase 16 Part D tests: org-level admin console (GET .../admin/workspaces).

Org-level only — no platform-superadmin concept is exercised or implied.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from apps.api.models.user import User
from apps.api.models.org_member import OrgMember
from apps.api.models.document import Document
from apps.api.models.connector import Connector

pytestmark = pytest.mark.asyncio


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


async def _seed_org_ws(client: AsyncClient, headers: dict) -> dict:
    org = (await client.post("/api/v1/organizations/", json={
        "name": "Admin Org", "slug": f"admin-{uuid.uuid4().hex[:8]}",
    }, headers=headers)).json()
    ws = (await client.post("/api/v1/workspaces/", json={
        "name": "Admin WS", "organization_id": org["id"],
    }, headers=headers)).json()
    return {"org": org, "ws": ws, "headers": headers}


async def test_admin_workspaces_reports_counts(client, db_session):
    headers = await _register_login(client, f"aowner-{uuid.uuid4().hex[:8]}@example.com")
    seed = await _seed_org_ws(client, headers)
    org_id = uuid.UUID(seed["org"]["id"])
    ws_id = uuid.UUID(seed["ws"]["id"])

    uploader = (await db_session.execute(
        select(User).join(OrgMember).where(OrgMember.organization_id == org_id)
    )).scalars().first()

    db_session.add(Document(
        title="D1", content_type="text/plain", status="INDEXED",
        file_path="d1.txt", workspace_id=ws_id, uploaded_by=uploader.id,
    ))
    db_session.add(Connector(
        organization_id=org_id, workspace_id=ws_id, provider="github", name="C1",
        connected_by=uploader.id,
    ))
    await db_session.commit()

    resp = await client.get(f"/api/v1/organizations/{org_id}/admin/workspaces", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["organization_id"] == str(org_id)
    assert body["member_count"] == 1
    assert len(body["workspaces"]) == 1
    ws_summary = body["workspaces"][0]
    assert ws_summary["id"] == str(ws_id)
    assert ws_summary["document_count"] == 1
    assert ws_summary["connector_count"] == 1
    assert ws_summary["workflow_count"] == 0
    assert ws_summary["creator_name"]


async def test_admin_workspaces_forbidden_for_member(client, db_session):
    owner_headers = await _register_login(client, f"aowner2-{uuid.uuid4().hex[:8]}@example.com")
    seed = await _seed_org_ws(client, owner_headers)
    org_id = seed["org"]["id"]

    member_email = f"amem-{uuid.uuid4().hex[:8]}@example.com"
    member_headers = await _register_login(client, member_email)
    member = (await db_session.execute(select(User).where(User.email == member_email))).scalar_one()
    db_session.add(OrgMember(user_id=member.id, organization_id=uuid.UUID(org_id), role="member"))
    await db_session.commit()

    resp = await client.get(f"/api/v1/organizations/{org_id}/admin/workspaces", headers=member_headers)
    assert resp.status_code == 403


async def test_admin_workspaces_forbidden_for_non_member(client, db_session):
    owner_headers = await _register_login(client, f"aowner3-{uuid.uuid4().hex[:8]}@example.com")
    seed = await _seed_org_ws(client, owner_headers)
    org_id = seed["org"]["id"]

    outsider_headers = await _register_login(client, f"outsider-{uuid.uuid4().hex[:8]}@example.com")
    resp = await client.get(f"/api/v1/organizations/{org_id}/admin/workspaces", headers=outsider_headers)
    assert resp.status_code == 403


async def test_admin_workspaces_not_found(client, db_session):
    headers = await _register_login(client, f"aowner4-{uuid.uuid4().hex[:8]}@example.com")
    resp = await client.get(
        f"/api/v1/organizations/{uuid.uuid4()}/admin/workspaces", headers=headers
    )
    assert resp.status_code == 403
