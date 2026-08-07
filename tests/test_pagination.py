"""Pagination tests for list endpoints and their envelope."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from apps.api.models.document import Document
from apps.api.models.user import User

pytestmark = pytest.mark.asyncio


async def _seed(client: AsyncClient, db_session, email: str):
    """Register a user with an org, workspace, and three documents.

    Documents are inserted directly through the DB session rather than via the
    upload endpoint, which would trigger the (very slow in the test env)
    worker/langchain import.
    """
    await client.post("/api/v1/auth/register", json={
        "email": email, "password": "strong1234567", "full_name": "P",
    })
    login = await client.post("/api/v1/auth/login", json={
        "email": email, "password": "strong1234567",
    })
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    org = (await client.post("/api/v1/organizations/", json={
        "name": f"Page Org {email}", "slug": f"page-{email.split('@')[0]}",
    }, headers=headers)).json()
    ws = (await client.post("/api/v1/workspaces/", json={
        "name": "WS", "organization_id": org["id"],
    }, headers=headers)).json()

    user = await db_session.scalar(select(User).where(User.email == email))
    for i in range(3):
        db_session.add(Document(
            title=f"doc-{i}.txt",
            content_type="text/plain",
            status="PENDING",
            workspace_id=uuid.UUID(ws["id"]),
            uploaded_by=user.id,
        ))
    await db_session.commit()
    return headers, org, ws


async def test_documents_paginated_envelope(client: AsyncClient, db_session):
    """List documents returns items/total/page/page_size/pages."""
    headers, _, ws = await _seed(client, db_session, "paginate@example.com")

    resp = await client.get(
        f"/api/v1/documents/?workspace_id={ws['id']}&page=1&page_size=2",
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert body["pages"] == 2
    assert len(body["items"]) == 2

    resp = await client.get(
        f"/api/v1/documents/?workspace_id={ws['id']}&page=2&page_size=2",
        headers=headers,
    )
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["total"] == 3


async def test_page_size_is_capped(client: AsyncClient, db_session):
    """Requesting a page_size above the cap is rejected by validation."""
    headers, org, _ = await _seed(client, db_session, "pagination-cap@example.com")
    resp = await client.get(
        f"/api/v1/workspaces/?organization_id={org['id']}&page_size=1000",
        headers=headers,
    )
    assert resp.status_code == 422


async def test_organizations_and_workspaces_paginated(client: AsyncClient, db_session):
    """Organizations and workspaces list endpoints use the same envelope."""
    headers, org, ws = await _seed(client, db_session, "paginate-orgs@example.com")

    orgs = (await client.get("/api/v1/organizations/", headers=headers)).json()
    assert orgs["total"] >= 1
    assert "items" in orgs and "pages" in orgs

    wss = (await client.get(
        f"/api/v1/workspaces/?organization_id={org['id']}",
        headers=headers,
    )).json()
    assert wss["total"] == 1
    assert wss["items"][0]["id"] == ws["id"]
