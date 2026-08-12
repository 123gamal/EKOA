"""Phase 13 tests: org invites, member management, workspace role overrides,
and the team activity feed.

Shared-conversation visibility (13-C) is covered in ``tests/test_phase4.py``
alongside the rest of the AI conversation persistence tests.
"""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

import apps.api.models  # noqa: F401  # register all models on Base
from apps.api.models.user import User
from apps.api.models.org_member import OrgMember
from apps.api.models.org_invite import OrgInvite
from apps.api.models.workspace_member import WorkspaceMember
from apps.api.services import email_service

pytestmark = pytest.mark.asyncio


# ── Helpers ──────────────────────────────────────────────────────────────────


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
        "name": "Team Org", "slug": f"team-{uuid.uuid4().hex[:8]}",
    }, headers=headers)).json()
    ws = (await client.post("/api/v1/workspaces/", json={
        "name": "Team WS", "organization_id": org["id"],
    }, headers=headers)).json()
    return {"org": org, "ws": ws, "headers": headers}


@pytest.fixture(autouse=True)
def stub_email(monkeypatch):
    """Never hit real SMTP in tests; record calls for assertions."""
    sent = []

    async def _fake_send(to, subject, html_body):
        sent.append({"to": to, "subject": subject, "html_body": html_body})

    monkeypatch.setattr(email_service, "send_email", _fake_send)
    return sent


# ── 13-A: Invites ────────────────────────────────────────────────────────────


async def test_invite_create_sends_email_stores_hash_only(client, db_session, stub_email):
    headers = await _register_login(client, f"inv-{uuid.uuid4().hex[:8]}@example.com")
    seed = await _seed_org_ws(client, headers)

    resp = await client.post(
        f"/api/v1/organizations/{seed['org']['id']}/invites",
        headers=headers,
        json={"email": "invitee@example.com", "role": "member"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email"] == "invitee@example.com"
    assert body["status"] == "pending"
    assert "token" not in body  # never returned via the API

    assert len(stub_email) == 1
    assert stub_email[0]["to"] == "invitee@example.com"
    assert "accept-invite?token=" in stub_email[0]["html_body"]

    row = (await db_session.execute(
        select(OrgInvite).where(OrgInvite.id == uuid.UUID(body["id"]))
    )).scalar_one()
    assert len(row.token_hash) == 64  # sha256 hex digest, not the raw token


async def test_invite_create_member_forbidden(client, db_session):
    owner_headers = await _register_login(client, f"iowner-{uuid.uuid4().hex[:8]}@example.com")
    seed = await _seed_org_ws(client, owner_headers)

    member_email = f"imem-{uuid.uuid4().hex[:8]}@example.com"
    member_headers = await _register_login(client, member_email)
    member = (await db_session.execute(select(User).where(User.email == member_email))).scalar_one()
    db_session.add(OrgMember(user_id=member.id, organization_id=uuid.UUID(seed["org"]["id"]), role="member"))
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/organizations/{seed['org']['id']}/invites",
        headers=member_headers,
        json={"email": "someone@example.com", "role": "member"},
    )
    assert resp.status_code == 403


async def test_invite_accept_creates_membership(client, db_session):
    owner_headers = await _register_login(client, f"aowner-{uuid.uuid4().hex[:8]}@example.com")
    seed = await _seed_org_ws(client, owner_headers)

    invitee_email = f"accept-{uuid.uuid4().hex[:8]}@example.com"
    create_resp = await client.post(
        f"/api/v1/organizations/{seed['org']['id']}/invites",
        headers=owner_headers,
        json={"email": invitee_email, "role": "admin"},
    )
    invite_id = uuid.UUID(create_resp.json()["id"])

    # The raw token only exists in the sent email and can't be recovered from
    # its hash (that's the point); overwrite the stored hash with one for a
    # known token so the accept call below can use it deterministically.
    org_row = (await db_session.execute(
        select(OrgInvite).where(OrgInvite.id == invite_id)
    )).scalar_one()
    # Overwrite with a known token+hash so the accept call can use it.
    raw_token = "test-raw-token-" + uuid.uuid4().hex
    org_row.token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    await db_session.commit()

    invitee_headers = await _register_login(client, invitee_email)
    resp = await client.post(
        "/api/v1/invites/accept", headers=invitee_headers, json={"token": raw_token}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "accepted"

    invitee = (await db_session.execute(select(User).where(User.email == invitee_email))).scalar_one()
    membership = (await db_session.execute(
        select(OrgMember).where(
            OrgMember.organization_id == uuid.UUID(seed["org"]["id"]),
            OrgMember.user_id == invitee.id,
        )
    )).scalar_one()
    assert membership.role == "admin"


async def test_invite_accept_wrong_email_rejected(client, db_session):
    owner_headers = await _register_login(client, f"wowner-{uuid.uuid4().hex[:8]}@example.com")
    seed = await _seed_org_ws(client, owner_headers)

    create_resp = await client.post(
        f"/api/v1/organizations/{seed['org']['id']}/invites",
        headers=owner_headers,
        json={"email": "intended@example.com", "role": "member"},
    )
    invite_id = uuid.UUID(create_resp.json()["id"])
    raw_token = "wrong-email-token-" + uuid.uuid4().hex
    row = (await db_session.execute(select(OrgInvite).where(OrgInvite.id == invite_id))).scalar_one()
    row.token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    await db_session.commit()

    someone_else_headers = await _register_login(client, f"else-{uuid.uuid4().hex[:8]}@example.com")
    resp = await client.post(
        "/api/v1/invites/accept", headers=someone_else_headers, json={"token": raw_token}
    )
    assert resp.status_code == 400


async def test_invite_accept_expired_rejected(client, db_session):
    owner_headers = await _register_login(client, f"eowner-{uuid.uuid4().hex[:8]}@example.com")
    seed = await _seed_org_ws(client, owner_headers)

    invitee_email = f"expired-{uuid.uuid4().hex[:8]}@example.com"
    create_resp = await client.post(
        f"/api/v1/organizations/{seed['org']['id']}/invites",
        headers=owner_headers,
        json={"email": invitee_email, "role": "member"},
    )
    invite_id = uuid.UUID(create_resp.json()["id"])
    raw_token = "expired-token-" + uuid.uuid4().hex
    row = (await db_session.execute(select(OrgInvite).where(OrgInvite.id == invite_id))).scalar_one()
    row.token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    row.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    await db_session.commit()

    invitee_headers = await _register_login(client, invitee_email)
    resp = await client.post(
        "/api/v1/invites/accept", headers=invitee_headers, json={"token": raw_token}
    )
    assert resp.status_code == 400


async def test_invite_revoke(client, db_session):
    owner_headers = await _register_login(client, f"rowner-{uuid.uuid4().hex[:8]}@example.com")
    seed = await _seed_org_ws(client, owner_headers)

    create_resp = await client.post(
        f"/api/v1/organizations/{seed['org']['id']}/invites",
        headers=owner_headers,
        json={"email": "revokeme@example.com", "role": "member"},
    )
    invite_id = create_resp.json()["id"]

    resp = await client.delete(
        f"/api/v1/organizations/{seed['org']['id']}/invites/{invite_id}", headers=owner_headers
    )
    assert resp.status_code == 204

    listed = await client.get(
        f"/api/v1/organizations/{seed['org']['id']}/invites", headers=owner_headers
    )
    assert all(item["id"] != invite_id for item in listed.json()["items"])


# ── 13-B: Member management ─────────────────────────────────────────────────


async def test_list_members(client, db_session):
    headers = await _register_login(client, f"lm-{uuid.uuid4().hex[:8]}@example.com")
    seed = await _seed_org_ws(client, headers)

    resp = await client.get(f"/api/v1/organizations/{seed['org']['id']}/members", headers=headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["role"] == "owner"


async def test_change_member_role_admin_only(client, db_session):
    owner_headers = await _register_login(client, f"cowner-{uuid.uuid4().hex[:8]}@example.com")
    seed = await _seed_org_ws(client, owner_headers)

    member_email = f"cmem-{uuid.uuid4().hex[:8]}@example.com"
    await _register_login(client, member_email)
    member = (await db_session.execute(select(User).where(User.email == member_email))).scalar_one()
    db_session.add(OrgMember(user_id=member.id, organization_id=uuid.UUID(seed["org"]["id"]), role="member"))
    await db_session.commit()

    resp = await client.patch(
        f"/api/v1/organizations/{seed['org']['id']}/members/{member.id}",
        headers=owner_headers,
        json={"role": "admin"},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"


async def test_cannot_demote_last_owner(client, db_session):
    owner_headers = await _register_login(client, f"lowner-{uuid.uuid4().hex[:8]}@example.com")
    seed = await _seed_org_ws(client, owner_headers)
    owner_user = (await db_session.execute(
        select(User).where(User.email.like("lowner-%"))
    )).scalars().first()

    resp = await client.patch(
        f"/api/v1/organizations/{seed['org']['id']}/members/{owner_user.id}",
        headers=owner_headers,
        json={"role": "member"},
    )
    assert resp.status_code == 400


async def test_remove_member(client, db_session):
    owner_headers = await _register_login(client, f"rmowner-{uuid.uuid4().hex[:8]}@example.com")
    seed = await _seed_org_ws(client, owner_headers)

    member_email = f"rmmem-{uuid.uuid4().hex[:8]}@example.com"
    await _register_login(client, member_email)
    member = (await db_session.execute(select(User).where(User.email == member_email))).scalar_one()
    db_session.add(OrgMember(user_id=member.id, organization_id=uuid.UUID(seed["org"]["id"]), role="member"))
    await db_session.commit()

    resp = await client.delete(
        f"/api/v1/organizations/{seed['org']['id']}/members/{member.id}", headers=owner_headers
    )
    assert resp.status_code == 204

    remaining = (await db_session.execute(
        select(OrgMember).where(
            OrgMember.organization_id == uuid.UUID(seed["org"]["id"]),
            OrgMember.user_id == member.id,
        )
    )).scalar_one_or_none()
    assert remaining is None


# ── 13-D: Workspace-level role overrides ────────────────────────────────────


async def test_workspace_role_override_falls_back_to_org_role(client, db_session):
    owner_headers = await _register_login(client, f"wowner-{uuid.uuid4().hex[:8]}@example.com")
    seed = await _seed_org_ws(client, owner_headers)

    member_email = f"wmem-{uuid.uuid4().hex[:8]}@example.com"
    await _register_login(client, member_email)
    member = (await db_session.execute(select(User).where(User.email == member_email))).scalar_one()
    db_session.add(OrgMember(user_id=member.id, organization_id=uuid.UUID(seed["org"]["id"]), role="member"))
    await db_session.commit()

    from apps.api.dependencies import authz

    # No override row yet: effective workspace role == org role ("member").
    role = await authz.get_workspace_role(
        db_session, member.id, uuid.UUID(seed["ws"]["id"]), uuid.UUID(seed["org"]["id"])
    )
    assert role == "member"

    resp = await client.put(
        f"/api/v1/workspaces/{seed['ws']['id']}/members/{member.id}",
        headers=owner_headers,
        json={"role": "admin"},
    )
    assert resp.status_code == 200

    override = (await db_session.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == uuid.UUID(seed["ws"]["id"]),
            WorkspaceMember.user_id == member.id,
        )
    )).scalar_one()
    assert override.role == "admin"


async def test_workspace_admin_override_permits_delete_denied_at_org_level(client, db_session):
    """A member with a workspace-admin override can delete that one workspace,
    even though their org-level role ('member') alone would forbid it."""
    owner_headers = await _register_login(client, f"downer-{uuid.uuid4().hex[:8]}@example.com")
    seed = await _seed_org_ws(client, owner_headers)

    member_email = f"dmem-{uuid.uuid4().hex[:8]}@example.com"
    member_headers = await _register_login(client, member_email)
    member = (await db_session.execute(select(User).where(User.email == member_email))).scalar_one()
    db_session.add(OrgMember(user_id=member.id, organization_id=uuid.UUID(seed["org"]["id"]), role="member"))
    await db_session.commit()

    # Without an override, a plain member cannot delete the workspace.
    denied = await client.delete(f"/api/v1/workspaces/{seed['ws']['id']}", headers=member_headers)
    assert denied.status_code == 403

    override_resp = await client.put(
        f"/api/v1/workspaces/{seed['ws']['id']}/members/{member.id}",
        headers=owner_headers,
        json={"role": "admin"},
    )
    assert override_resp.status_code == 200

    allowed = await client.delete(f"/api/v1/workspaces/{seed['ws']['id']}", headers=member_headers)
    assert allowed.status_code == 204


# ── 13-E: Activity feed ─────────────────────────────────────────────────────


async def test_activity_feed_scoped_to_org(client, db_session):
    headers_a = await _register_login(client, f"acta-{uuid.uuid4().hex[:8]}@example.com")
    seed_a = await _seed_org_ws(client, headers_a)

    headers_b = await _register_login(client, f"actb-{uuid.uuid4().hex[:8]}@example.com")
    seed_b = await _seed_org_ws(client, headers_b)

    resp = await client.get(f"/api/v1/organizations/{seed_a['org']['id']}/activity", headers=headers_a)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) >= 1
    assert all(
        item["details"] is None or item["details"].get("organization_id", str(seed_a["org"]["id"])) is not None
        for item in items
    )
    # No cross-tenant leakage: org B's activity is invisible to org A's owner.
    resp_forbidden = await client.get(
        f"/api/v1/organizations/{seed_b['org']['id']}/activity", headers=headers_a
    )
    assert resp_forbidden.status_code == 403
