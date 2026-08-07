"""Phase 4 tests: conversation persistence, document versioning, soft deletes, Qdrant tenant filtering."""

import sys
import types
import uuid
import hashlib

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from apps.api.db.engine import get_db
from apps.api.models.user import User
from apps.api.models.organization import Organization
from apps.api.models.org_member import OrgMember
from apps.api.models.workspace import Workspace
from apps.api.models.document import Document
from apps.api.models.workflow import Workflow
from apps.api.models.audit_log import AuditLog
from apps.ai.main import app as ai_app
from apps.ai.deps import get_current_user as ai_get_current_user
from apps.ai import main as ai_main

pytestmark = pytest.mark.asyncio


# ── AI conversation persistence ──────────────────────────────────────────────


class FakeGraph:
    """Records the state passed to the graph and returns a deterministic answer."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def ainvoke(self, state: dict) -> dict:
        self.calls.append(state)
        return {
            "final_answer": "fake assistant reply",
            "context_chunks": [],
            "actions": [],
            "degraded": False,
        }


@pytest.fixture
async def ai_env(db_session, monkeypatch):
    """Wire the AI app to the test DB with a deterministic graph.

    Overrides both the DB dependency and the auth dependency so no real JWT or
    Postgres is needed, and replaces the graph so no LLM/Qdrant/embedding call
    happens. Returns (client, user, workspace, fake_graph).
    """
    user = User(
        email=f"ai-{uuid.uuid4().hex[:10]}@example.com",
        full_name="AI Test User",
        hashed_password="x",
    )
    db_session.add(user)
    await db_session.flush()
    org = Organization(
        name="AI Org",
        slug=f"ai-org-{uuid.uuid4().hex[:8]}",
        owner_id=user.id,
    )
    db_session.add(org)
    await db_session.flush()
    db_session.add(OrgMember(user_id=user.id, organization_id=org.id, role="owner"))
    workspace = Workspace(
        name="AI Workspace",
        organization_id=org.id,
        created_by=user.id,
    )
    db_session.add(workspace)
    await db_session.commit()

    fake_graph = FakeGraph()

    async def _override_db():
        yield db_session

    async def _override_user():
        return user

    monkeypatch.setattr(ai_main, "get_agent_graph", lambda: fake_graph)

    ai_app.dependency_overrides[get_db] = _override_db
    ai_app.dependency_overrides[ai_get_current_user] = _override_user
    transport = ASGITransport(app=ai_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac, user, workspace, fake_graph
    ai_app.dependency_overrides.clear()


async def test_chat_creates_conversation_and_persists_messages(ai_env):
    client, _user, workspace, fake_graph = ai_env
    resp = await client.post("/api/v1/ai/chat", json={
        "workspace_id": str(workspace.id),
        "message": "hello EKOA",
    })
    assert resp.status_code == 200
    body = resp.json()
    conv_id = body["conversation_id"]
    assert conv_id
    assert body["reply"] == "fake assistant reply"

    # Exactly one conversation, first message seeded from client history fallback.
    assert len(fake_graph.calls) == 1
    assert fake_graph.calls[0]["messages"] == [{"role": "user", "content": "hello EKOA"}]

    listing = await client.get(f"/api/v1/ai/conversations?workspace_id={workspace.id}")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1

    msgs = await client.get(f"/api/v1/ai/conversations/{conv_id}/messages")
    assert msgs.status_code == 200
    items = msgs.json()["items"]
    assert [m["role"] for m in items] == ["user", "assistant"]
    assert items[0]["content"] == "hello EKOA"
    assert items[1]["content"] == "fake assistant reply"


async def test_chat_reloads_history_from_db(ai_env):
    """The second turn's graph state must include prior turns loaded from the DB.

    The client sends no ``history`` on the second request, so any prior context
    in the state can only have come from the persisted conversation rows.
    """
    client, _user, workspace, fake_graph = ai_env

    r1 = await client.post("/api/v1/ai/chat", json={
        "workspace_id": str(workspace.id),
        "message": "first question",
    })
    conv_id = r1.json()["conversation_id"]

    r2 = await client.post("/api/v1/ai/chat", json={
        "workspace_id": str(workspace.id),
        "conversation_id": conv_id,
        "message": "second question",
    })
    assert r2.status_code == 200

    # The DB reloaded turn 1 (user + assistant) and appended turn 2's message.
    second_state = fake_graph.calls[1]["messages"]
    assert second_state == [
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "fake assistant reply"},
        {"role": "user", "content": "second question"},
    ]

    # Full persisted history is 4 messages.
    msgs = await client.get(f"/api/v1/ai/conversations/{conv_id}/messages")
    items = msgs.json()["items"]
    assert len(items) == 4
    assert [m["role"] for m in items] == ["user", "assistant", "user", "assistant"]


async def test_chat_unknown_conversation_404(ai_env):
    client, _user, workspace, _fake = ai_env
    resp = await client.post("/api/v1/ai/chat", json={
        "workspace_id": str(workspace.id),
        "conversation_id": str(uuid.uuid4()),
        "message": "hello",
    })
    assert resp.status_code == 404


async def test_messages_endpoint_scoped_to_owner(ai_env, db_session):
    client, user, workspace, _fake = ai_env

    # A second user's conversation in the same workspace must be invisible.
    other = User(
        email=f"ai-other-{uuid.uuid4().hex[:10]}@example.com",
        full_name="Other",
        hashed_password="x",
    )
    db_session.add(other)
    await db_session.flush()
    from apps.api.models.conversation import Conversation

    other_conv = Conversation(
        title="other",
        workspace_id=workspace.id,
        organization_id=workspace.organization_id,
        user_id=other.id,
    )
    db_session.add(other_conv)
    await db_session.commit()

    resp = await client.get(f"/api/v1/ai/conversations/{other_conv.id}/messages")
    assert resp.status_code == 404

    # Own conversations list only contains the caller's rows.
    resp = await client.get(f"/api/v1/ai/conversations?workspace_id={workspace.id}")
    assert resp.status_code == 200
    assert all(item["user_id"] == str(user.id) for item in resp.json()["items"])


# ── Document versioning ──────────────────────────────────────────────────────


async def _register_login(client: AsyncClient, email: str) -> dict:
    resp = await client.post("/api/v1/auth/register", json={
        "email": email, "password": "strongpassword123", "full_name": "Test User",
    })
    assert resp.status_code in (201, 211)
    resp = await client.post("/api/v1/auth/login", json={
        "email": email, "password": "strongpassword123",
    })
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_document_upload_creates_version_one(client, monkeypatch):
    headers = await _register_login(client, f"docver-{uuid.uuid4().hex[:8]}@example.com")
    org = (await client.post("/api/v1/organizations/", json={
        "name": "DV Org", "slug": f"dv-{uuid.uuid4().hex[:8]}",
    }, headers=headers)).json()
    ws = (await client.post("/api/v1/workspaces/", json={
        "name": "DV WS", "organization_id": org["id"],
    }, headers=headers)).json()

    # Stub the Celery task import so no worker dependencies load in tests.
    fake_tasks = types.ModuleType("apps.worker.tasks")
    fake_tasks.process_document = types.SimpleNamespace(delay=lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, "apps.worker.tasks", fake_tasks)

    content = b"Enterprise document content for the versioning test."
    resp = await client.post(
        "/api/v1/documents/upload",
        headers=headers,
        data={"workspace_id": ws["id"]},
        files={"file": ("report.txt", content, "text/plain")},
    )
    assert resp.status_code == 201
    doc = resp.json()

    versions = (await client.get(f"/api/v1/documents/{doc['id']}/versions", headers=headers)).json()
    assert len(versions["items"]) == 1
    v = versions["items"][0]
    assert v["version"] == 1
    assert v["checksum"] == hashlib.sha256(content).hexdigest()
    assert v["status"] == "PENDING"


# ── Soft deletes ─────────────────────────────────────────────────────────────


async def test_soft_delete_document_hides_from_lists_and_get(client, db_session):
    headers = await _register_login(client, f"sd-doc-{uuid.uuid4().hex[:8]}@example.com")
    org = (await client.post("/api/v1/organizations/", json={
        "name": "SD Org", "slug": f"sd-{uuid.uuid4().hex[:8]}",
    }, headers=headers)).json()
    ws = (await client.post("/api/v1/workspaces/", json={
        "name": "SD WS", "organization_id": org["id"],
    }, headers=headers)).json()

    doc = Document(
        title="to delete", content_type="text/plain", status="INDEXED",
        file_path="/tmp/x.txt", workspace_id=uuid.UUID(ws["id"]), uploaded_by=uuid.UUID(org["owner_id"]),
    )
    db_session.add(doc)
    await db_session.commit()

    resp = await client.delete(f"/api/v1/documents/{doc.id}", headers=headers)
    assert resp.status_code == 204

    listing = (await client.get(f"/api/v1/documents/?workspace_id={ws['id']}", headers=headers)).json()
    assert listing["total"] == 0

    get = await client.get(f"/api/v1/documents/{doc.id}", headers=headers)
    assert get.status_code == 404

    audit = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == "document.delete")
    )).scalars().all()
    assert len(audit) >= 1
    assert str(audit[-1].resource_id) == str(doc.id)


async def test_soft_delete_workspace_and_organization(client):
    headers = await _register_login(client, f"sd-org-{uuid.uuid4().hex[:8]}@example.com")
    org = (await client.post("/api/v1/organizations/", json={
        "name": "SD Org2", "slug": f"sd2-{uuid.uuid4().hex[:8]}",
    }, headers=headers)).json()
    ws = (await client.post("/api/v1/workspaces/", json={
        "name": "SD WS2", "organization_id": org["id"],
    }, headers=headers)).json()

    # Workspace soft-delete: admin (owner) succeeds, subsequent reads 404.
    resp = await client.delete(f"/api/v1/workspaces/{ws['id']}", headers=headers)
    assert resp.status_code == 204
    assert (await client.get(f"/api/v1/workspaces/{ws['id']}", headers=headers)).status_code == 404
    ws_list = (await client.get(f"/api/v1/workspaces/?organization_id={org['id']}", headers=headers)).json()
    assert ws_list["total"] == 0

    # Organization soft-delete: owner only, subsequent reads 404 and list empty.
    resp = await client.delete(f"/api/v1/organizations/{org['slug']}", headers=headers)
    assert resp.status_code == 204
    assert (await client.get(f"/api/v1/organizations/{org['slug']}", headers=headers)).status_code == 404
    org_list = (await client.get("/api/v1/organizations/", headers=headers)).json()
    assert all(item["slug"] != org["slug"] for item in org_list["items"])


async def test_soft_delete_workflow(client, db_session):
    headers = await _register_login(client, f"sd-wf-{uuid.uuid4().hex[:8]}@example.com")
    org = (await client.post("/api/v1/organizations/", json={
        "name": "SD Org3", "slug": f"sd3-{uuid.uuid4().hex[:8]}",
    }, headers=headers)).json()
    ws = (await client.post("/api/v1/workspaces/", json={
        "name": "SD WS3", "organization_id": org["id"],
    }, headers=headers)).json()

    workflow = Workflow(
        name="to delete", template_id="tpl-1", status="DRAFT",
        workspace_id=uuid.UUID(ws["id"]), created_by=uuid.UUID(org["owner_id"]),
    )
    db_session.add(workflow)
    await db_session.commit()

    resp = await client.delete(f"/api/v1/workflows/{workflow.id}", headers=headers)
    assert resp.status_code == 204
    assert (await client.get(f"/api/v1/workflows/{workflow.id}", headers=headers)).status_code == 404
    wf_list = (await client.get(f"/api/v1/workflows/?workspace_id={ws['id']}", headers=headers)).json()
    assert wf_list["total"] == 0


# ── Qdrant tenant filtering ──────────────────────────────────────────────────


async def test_tenant_filter_construction():
    from apps.ai.retriever import _tenant_filter

    f = _tenant_filter("org-1", "ws-1")
    assert f is not None
    keys = {c.key for c in f.must}
    assert keys == {"organization_id", "workspace_id"}

    only_org = _tenant_filter("org-1", None)
    assert [c.key for c in only_org.must] == ["organization_id"]

    none = _tenant_filter(None, None)
    assert none is None


async def test_retrieve_chunks_passes_tenant_filter(monkeypatch):
    from apps.ai import retriever

    class FakeEmbedder:
        def encode(self, texts, show_progress_bar=False):
            class Vec:
                def tolist(self):
                    return [0.1, 0.2, 0.3]
            return [Vec()]

    captured: dict = {}

    class FakeClient:
        def query_points(self, **kwargs):
            captured.update(kwargs)
            return types.SimpleNamespace(points=[])

    monkeypatch.setattr(retriever, "_get_embedder", lambda: FakeEmbedder())
    monkeypatch.setattr(retriever, "_get_qdrant", lambda: FakeClient())

    retriever.retrieve_chunks(
        "query",
        collection_name="ekoa_abcdef12",
        organization_id="11111111-1111-1111-1111-111111111111",
        workspace_id="22222222-2222-2222-2222-222222222222",
    )

    query_filter = captured["query_filter"]
    assert query_filter is not None
    assert {c.key for c in query_filter.must} == {"organization_id", "workspace_id"}
    match_org = next(c for c in query_filter.must if c.key == "organization_id")
    assert match_org.match.value == "11111111-1111-1111-1111-111111111111"
