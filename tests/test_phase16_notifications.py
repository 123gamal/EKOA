"""Phase 16 Part B-3 tests: Notification model/service/routes + graph node,
plus the two real trigger points (workflow approval-pause, connector sync
permanent failure)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import apps.api.models  # noqa: F401  # register all models on Base
from apps.api.db.base import Base
from apps.api.models.notification import Notification
from apps.api.models.organization import Organization
from apps.api.models.user import User
from apps.api.models.workspace import Workspace
from apps.api.services import email_service, notification_service


async def _register_login(client, email: str) -> dict:
    resp = await client.post("/api/v1/auth/register", json={
        "email": email, "password": "strongpassword123", "full_name": "Test User",
    })
    assert resp.status_code in (201, 211), resp.text
    resp = await client.post("/api/v1/auth/login", json={
        "email": email, "password": "strongpassword123",
    })
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture(autouse=True)
def stub_email(monkeypatch):
    sent = []

    async def _fake_send(to, subject, html_body):
        sent.append({"to": to, "subject": subject, "html_body": html_body})

    monkeypatch.setattr(email_service, "send_email", _fake_send)
    return sent


# ── Async notify() ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notify_creates_row_and_sends_email(db_session, stub_email):
    user = User(email=f"nt-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name="U")
    db_session.add(user)
    await db_session.flush()

    notification = await notification_service.notify(
        db_session,
        user_id=user.id,
        organization_id=None,
        type="workflow.approval_needed",
        title="Approval needed",
        body="A run is paused.",
        email_to=user.email,
    )

    assert notification.id is not None
    assert notification.read_at is None
    row = (await db_session.execute(
        select(Notification).where(Notification.id == notification.id)
    )).scalar_one()
    assert row.title == "Approval needed"
    assert len(stub_email) == 1
    assert stub_email[0]["to"] == user.email


@pytest.mark.asyncio
async def test_notify_without_email_to_sends_no_email(db_session, stub_email):
    user = User(email=f"nt2-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name="U")
    db_session.add(user)
    await db_session.flush()

    await notification_service.notify(
        db_session, user_id=user.id, organization_id=None,
        type="connector.sync_failed", title="Sync failed",
    )
    assert stub_email == []


# ── Sync notify_sync() (worker context) ─────────────────────────────────────


def _sync_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def test_notify_sync_creates_row(monkeypatch):
    sent = []
    monkeypatch.setattr(email_service, "_send_sync", lambda to, subj, body: sent.append(to))

    engine = _sync_engine()
    with Session(engine) as db:
        user = User(email="sync-notify@example.com", hashed_password="x", full_name="U")
        db.add(user)
        db.commit()

        notification = notification_service.notify_sync(
            db, user_id=user.id, organization_id=None,
            type="workflow.approval_needed", title="Approval needed",
            email_to=user.email,
        )
        assert notification.id is not None
        row = db.query(Notification).filter(Notification.id == notification.id).first()
        assert row is not None
        assert row.title == "Approval needed"
    assert sent == ["sync-notify@example.com"]


# ── Real trigger points ─────────────────────────────────────────────────────


def test_workflow_approval_pause_creates_notification(monkeypatch):
    """The exact wiring in apps/worker/workflow_executor.py: when a run
    pauses for approval, the workflow's creator gets a real Notification row."""
    from apps.worker import workflow_executor

    sent = []
    monkeypatch.setattr(email_service, "_send_sync", lambda to, subj, body: sent.append(to))

    engine = _sync_engine()
    with Session(engine) as db:
        user = User(email="creator@example.com", hashed_password="x", full_name="Creator")
        db.add(user)
        db.commit()
        org = Organization(name="Org", slug=f"o-{uuid.uuid4().hex[:8]}", owner_id=user.id)
        db.add(org)
        db.commit()
        ws = Workspace(name="WS", organization_id=org.id, created_by=user.id)
        db.add(ws)
        db.commit()

        from apps.api.models.workflow import Workflow, WorkflowRun
        wf = Workflow(name="Compliance", template_id="compliance-audit", workspace_id=ws.id, created_by=user.id)
        db.add(wf)
        db.commit()
        run = WorkflowRun(workflow_id=wf.id, status="AWAITING_APPROVAL")
        db.add(run)
        db.commit()

        workflow_executor._notify_approval_needed(db, wf, run)

        rows = db.query(Notification).filter(Notification.user_id == user.id).all()
        assert len(rows) == 1
        assert rows[0].type == "workflow.approval_needed"
        assert rows[0].resource_id == run.id
    assert sent == ["creator@example.com"]


def test_workflow_approval_notification_failure_does_not_raise():
    """A broken notification path (e.g. missing FK data) must not fail the
    workflow run itself — the helper swallows and logs."""
    from apps.worker import workflow_executor

    class _BrokenSession:
        def query(self, *a, **k):
            raise RuntimeError("boom")

    class _FakeWf:
        id = uuid.uuid4()
        created_by = uuid.uuid4()
        workspace_id = uuid.uuid4()
        name = "X"

    class _FakeRun:
        id = uuid.uuid4()

    # Must not raise.
    workflow_executor._notify_approval_needed(_BrokenSession(), _FakeWf(), _FakeRun())


def test_connector_sync_failed_creates_notification(monkeypatch):
    from apps.worker import tasks as worker_tasks

    sent = []
    monkeypatch.setattr(email_service, "_send_sync", lambda to, subj, body: sent.append(to))

    engine = _sync_engine()
    with Session(engine) as db:
        user = User(email="connector-owner@example.com", hashed_password="x", full_name="Owner")
        db.add(user)
        db.commit()
        org = Organization(name="Org2", slug=f"o2-{uuid.uuid4().hex[:8]}", owner_id=user.id)
        db.add(org)
        db.commit()
        ws = Workspace(name="WS2", organization_id=org.id, created_by=user.id)
        db.add(ws)
        db.commit()

        from apps.api.models.connector import Connector
        connector = Connector(
            organization_id=org.id, workspace_id=ws.id, provider="jira", name="Jira",
            connected_by=user.id,
        )
        db.add(connector)
        db.commit()

        worker_tasks._notify_connector_sync_failed(db, connector, "token invalid")

        rows = db.query(Notification).filter(Notification.user_id == user.id).all()
        assert len(rows) == 1
        assert rows[0].type == "connector.sync_failed"
        assert "token invalid" in rows[0].body
    assert sent == ["connector-owner@example.com"]


# ── HTTP routes ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_notifications_scoped_to_current_user(client, db_session):
    headers = await _register_login(client, f"ntroute-{uuid.uuid4().hex[:8]}@example.com")
    me = await client.get("/api/v1/auth/me", headers=headers)
    my_id = uuid.UUID(me.json()["id"])

    other_user = User(email=f"other-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name="Other")
    db_session.add(other_user)
    await db_session.flush()

    db_session.add(Notification(user_id=my_id, type="workflow.approval_needed", title="Mine 1"))
    db_session.add(Notification(user_id=my_id, type="connector.sync_failed", title="Mine 2"))
    db_session.add(Notification(user_id=other_user.id, type="workflow.approval_needed", title="Not mine"))
    await db_session.commit()

    resp = await client.get("/api/v1/notifications/", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    titles = {item["title"] for item in body["items"]}
    assert titles == {"Mine 1", "Mine 2"}


@pytest.mark.asyncio
async def test_unread_count_route(client, db_session):
    headers = await _register_login(client, f"ntunread-{uuid.uuid4().hex[:8]}@example.com")
    me = await client.get("/api/v1/auth/me", headers=headers)
    my_id = uuid.UUID(me.json()["id"])

    db_session.add(Notification(user_id=my_id, type="x", title="Unread 1"))
    db_session.add(Notification(user_id=my_id, type="x", title="Unread 2"))
    await db_session.commit()

    resp = await client.get("/api/v1/notifications/unread-count", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["unread_count"] == 2


@pytest.mark.asyncio
async def test_mark_read_route_rejects_other_users_notification(client, db_session):
    headers = await _register_login(client, f"ntmark-{uuid.uuid4().hex[:8]}@example.com")

    other_user = User(email=f"other2-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name="Other")
    db_session.add(other_user)
    await db_session.flush()
    other_notification = Notification(user_id=other_user.id, type="x", title="Not yours")
    db_session.add(other_notification)
    await db_session.commit()
    await db_session.refresh(other_notification)

    resp = await client.post(f"/api/v1/notifications/{other_notification.id}/read", headers=headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_mark_read_route_marks_own_notification(client, db_session):
    headers = await _register_login(client, f"ntmark2-{uuid.uuid4().hex[:8]}@example.com")
    me = await client.get("/api/v1/auth/me", headers=headers)
    my_id = uuid.UUID(me.json()["id"])

    n = Notification(user_id=my_id, type="x", title="Mark me")
    db_session.add(n)
    await db_session.commit()
    await db_session.refresh(n)

    resp = await client.post(f"/api/v1/notifications/{n.id}/read", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["read_at"] is not None


# ── Graph node ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notification_node_reports_unread(monkeypatch, db_session):
    import apps.api.db.engine as engine_mod
    from apps.ai.graph import notification_node
    from tests.conftest import async_session_factory as conftest_session_factory

    monkeypatch.setattr(engine_mod, "get_session_factory", lambda: conftest_session_factory)

    user = User(email=f"ntnode-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name="U")
    db_session.add(user)
    await db_session.flush()
    db_session.add(Notification(user_id=user.id, type="x", title="Hello there"))
    await db_session.commit()

    state = {
        "messages": [{"role": "user", "content": "do I have notifications?"}],
        "actions": [],
        "user_id": str(user.id),
    }
    result = await notification_node(state)
    assert "Hello there" in result["final_answer"]
    assert result["actions"][-1]["tool_name"] == "notifications.summary"


@pytest.mark.asyncio
async def test_notification_node_no_notifications(monkeypatch, db_session):
    import apps.api.db.engine as engine_mod
    from apps.ai.graph import notification_node
    from tests.conftest import async_session_factory as conftest_session_factory

    monkeypatch.setattr(engine_mod, "get_session_factory", lambda: conftest_session_factory)

    state = {"messages": [], "actions": [], "user_id": str(uuid.uuid4())}
    result = await notification_node(state)
    assert "no notifications" in result["final_answer"].lower()
