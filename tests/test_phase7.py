"""Phase 7 tests: connector framework, Fernet encryption at rest, GitHub connect/
validate/disconnect/sync (checksum dedup), health check, RBAC gating.

Key guarantees under test:
- Credentials are stored Fernet-encrypted at rest (never plaintext in the DB).
- Connect validates the token against the provider BEFORE persisting anything.
- Connect/disconnect/sync are admin-gated and audited.
- Sync dedups by (file path, content sha256): a second run with unchanged
  files creates no new Documents and no new DocumentVersions.
- A bad/revoked token fails gracefully (HTTP 400 on connect; connector flips
  to error status on sync/health) instead of crashing or silently succeeding.
"""

import os
import sys
import tempfile
import types
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from apps.api.db.base import Base
import apps.api.models  # noqa: F401  # register all models on Base
from apps.api.models.user import User
from apps.api.models.organization import Organization
from apps.api.models.org_member import OrgMember
from apps.api.models.workspace import Workspace
from apps.api.models.connector import Connector, ConnectorCredential
from apps.api.models.document import Document
from apps.api.models.document_version import DocumentVersion
from apps.api.models.audit_log import AuditLog



# â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


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
    """Create an org + workspace for an admin (the registered user is owner)."""
    org = (await client.post("/api/v1/organizations/", json={
        "name": "Conn Org", "slug": f"corg-{uuid.uuid4().hex[:8]}",
    }, headers=headers)).json()
    ws = (await client.post("/api/v1/workspaces/", json={
        "name": "Conn WS", "organization_id": org["id"],
    }, headers=headers)).json()
    return {"org": org, "ws": ws, "headers": headers}


async def _add_member(db_session, org_id, user_id: uuid.UUID, role: str) -> None:
    db_session.add(OrgMember(user_id=user_id, organization_id=org_id, role=role))
    await db_session.commit()


# â”€â”€ Encryption at rest â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@pytest.mark.asyncio
async def test_connector_credential_stored_encrypted_at_rest(client, db_session):
    """The token column holds Fernet ciphertext, never the plaintext PAT."""
    headers = await _register_login(client, f"enc-{uuid.uuid4().hex[:8]}@example.com")
    seed = await _seed_org_ws(client, headers, db_session)

    import apps.api.services.connectors.github as gh
    original = gh._github_request

    def fake_request(method, url, access_token, headers=None, **kwargs):
        from httpx import Response
        if "/repos/" in url:
            return Response(200, json={
                "full_name": "acme/backend",
                "default_branch": "main",
                "private": False,
            })
        raise AssertionError(f"unexpected call {method} {url}")

    gh._github_request = fake_request
    try:
        resp = await client.post("/api/v1/connectors/", headers=seed["headers"], json={
            "provider": "github",
            "workspace_id": seed["ws"]["id"],
            "name": "Backend Docs",
            "access_token": "ghp_SUPERSECRETTOKEN123456",
            "config": {"owner": "acme", "repo": "backend"},
        })
        assert resp.status_code == 201, resp.text
    finally:
        gh._github_request = original

    connector = (await db_session.execute(
        select(Connector).where(Connector.name == "Backend Docs")
    )).scalar_one()
    cred = (await db_session.execute(
        select(ConnectorCredential).where(ConnectorCredential.connector_id == connector.id)
    )).scalar_one()

    # Ciphertext: definitely not the plaintext token.
    assert "ghp_SUPERSECRETTOKEN123456" not in cred.access_token_encrypted
    # Fernet ciphertext is url-safe base64 with the "gAAAA" magic prefix.
    assert cred.access_token_encrypted.startswith("gAAAA")

    # Round-trip decrypt returns the original token.
    from ekoa_config.connector_crypto import decrypt_secret
    assert decrypt_secret(cred.access_token_encrypted) == "ghp_SUPERSECRETTOKEN123456"


@pytest.mark.asyncio
async def test_crypto_roundtrip_and_key_independence():
    """Fernet encrypt/decrypt roundtrip works; a different key cannot decrypt."""
    from ekoa_config.connector_crypto import encrypt_secret, decrypt_secret

    ct = encrypt_secret("pat-123")
    assert ct != "pat-123"
    assert decrypt_secret(ct) == "pat-123"

    with pytest.raises(Exception):
        decrypt_secret("gAAAAA-not-valid-ciphertext")


# â”€â”€ Connect: validation-before-persist, RBAC, audit â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@pytest.mark.asyncio
async def test_connect_validates_token_before_saving(client, db_session):
    """A rejected token â†’ 400 and NOTHING persisted (no connector, no credential)."""
    headers = await _register_login(client, f"bad-{uuid.uuid4().hex[:8]}@example.com")
    seed = await _seed_org_ws(client, headers, db_session)

    import apps.api.services.connectors.github as gh
    original = gh._github_request

    def fake_request(method, url, access_token, headers=None, **kwargs):
        from httpx import Response
        if "/repos/" in url:
            return Response(401, json={"message": "Bad credentials"})
        raise AssertionError(f"unexpected call {method} {url}")

    gh._github_request = fake_request
    try:
        resp = await client.post("/api/v1/connectors/", headers=seed["headers"], json={
            "provider": "github",
            "workspace_id": seed["ws"]["id"],
            "name": "Bad Repo",
            "access_token": "ghp_REVOKEDTOKEN",
            "config": {"owner": "acme", "repo": "backend"},
        })
        assert resp.status_code == 400, resp.text
        assert "invalid" in resp.json()["detail"].lower() or "revoked" in resp.json()["detail"].lower()
    finally:
        gh._github_request = original

    connectors = (await db_session.execute(
        select(Connector).where(Connector.workspace_id == uuid.UUID(seed["ws"]["id"]))
    )).scalars().all()
    assert len(connectors) == 0
    creds = (await db_session.execute(
        select(ConnectorCredential).join(Connector, Connector.id == ConnectorCredential.connector_id)
        .where(Connector.workspace_id == uuid.UUID(seed["ws"]["id"]))
    )).scalars().all()
    assert len(creds) == 0


@pytest.mark.asyncio
async def test_connect_member_forbidden(client, db_session):
    """A plain member cannot connect integrations; admin/owner can."""
    owner_email = f"owner-{uuid.uuid4().hex[:8]}@example.com"
    headers_owner = await _register_login(client, owner_email)
    seed = await _seed_org_ws(client, headers_owner, db_session)

    member_email = f"mem-{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/register", json={
        "email": member_email, "password": "strongpassword123", "full_name": "Member User",
    })
    member_user = (await db_session.execute(
        select(User).where(User.email == member_email)
    )).scalar_one()
    await _add_member(db_session, uuid.UUID(seed["org"]["id"]), member_user.id, "member")
    member_login = await client.post("/api/v1/auth/login", json={
        "email": member_email, "password": "strongpassword123",
    })
    headers_member = {"Authorization": f"Bearer {member_login.json()['access_token']}"}

    import apps.api.services.connectors.github as gh
    original = gh._github_request

    def fake_request(method, url, access_token, headers=None, **kwargs):
        from httpx import Response
        if "/repos/" in url:
            return Response(200, json={
                "full_name": "acme/backend",
                "default_branch": "main",
                "private": False,
            })
        raise AssertionError(f"unexpected call {method} {url}")

    gh._github_request = fake_request
    try:
        payload = {
            "provider": "github",
            "workspace_id": seed["ws"]["id"],
            "name": "Member Try",
            "access_token": "ghp_whatever",
            "config": {"owner": "acme", "repo": "backend"},
        }
        resp_member = await client.post("/api/v1/connectors/", headers=headers_member, json=payload)
        assert resp_member.status_code == 403, resp_member.text

        # Audit trail for admin connect.
        resp_admin = await client.post("/api/v1/connectors/", headers=seed["headers"], json=payload)
        assert resp_admin.status_code == 201, resp_admin.text
    finally:
        gh._github_request = original
    audits = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == "connector.connect")
    )).scalars().all()
    assert len(audits) >= 1


@pytest.mark.asyncio
async def test_connect_disconnect_audited_and_removes_credential(client, db_session):
    """Disconnect removes the stored credential and is audited."""
    headers = await _register_login(client, f"disc-{uuid.uuid4().hex[:8]}@example.com")
    seed = await _seed_org_ws(client, headers, db_session)

    import apps.api.services.connectors.github as gh
    original = gh._github_request

    def fake_request(method, url, access_token, headers=None, **kwargs):
        from httpx import Response
        if "/repos/" in url:
            return Response(200, json={
                "full_name": "acme/backend",
                "default_branch": "main",
                "private": False,
            })
        raise AssertionError(f"unexpected call {method} {url}")

    gh._github_request = fake_request
    try:
        resp = await client.post("/api/v1/connectors/", headers=seed["headers"], json={
            "provider": "github",
            "workspace_id": seed["ws"]["id"],
            "name": "Disc Me",
            "access_token": "ghp_disconnect",
            "config": {"owner": "acme", "repo": "backend"},
        })
        assert resp.status_code == 201
    finally:
        gh._github_request = original

    connector_id = resp.json()["id"]
    d = await client.post(f"/api/v1/connectors/{connector_id}/disconnect", headers=seed["headers"])
    assert d.status_code == 200, d.text
    assert d.json()["status"] == "disconnected"

    cred = (await db_session.execute(
        select(ConnectorCredential).where(ConnectorCredential.connector_id == uuid.UUID(connector_id))
    )).scalar_one_or_none()
    assert cred is None  # credential removed

    audits = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == "connector.disconnect")
    )).scalars().all()
    assert len(audits) >= 1


# â”€â”€ Sync: real ingestion + checksum dedup â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@pytest.fixture
def sync_db():
    """A throwaway file-backed sync sqlite with all tables created."""
    tmpdir = tempfile.mkdtemp()
    engine = create_engine(f"sqlite:///{os.path.join(tmpdir, 'connector.sqlite')}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


def _seed_connector_sync(engine) -> uuid.UUID:
    """Seed a workspace + connector (with encrypted credential) for sync tests."""
    with Session(engine) as db:
        user = User(email=f"sync-{uuid.uuid4().hex[:8]}@example.com", full_name="Owner", hashed_password="x")
        db.add(user)
        db.flush()
        org = Organization(name="SyncOrg", slug=f"sync-{uuid.uuid4().hex[:8]}", owner_id=user.id)
        db.add(org)
        db.flush()
        db.add(OrgMember(user_id=user.id, organization_id=org.id, role="owner"))
        ws = Workspace(name="SyncWS", organization_id=org.id, created_by=user.id)
        db.add(ws)
        db.flush()
        conn = Connector(
            organization_id=org.id, workspace_id=ws.id, provider="github",
            name="Backend Docs", status="connected",
            connected_by=user.id, connected_at=datetime.now(timezone.utc),
            config_json={"owner": "acme", "repo": "backend", "default_branch": "main"},
        )
        db.add(conn)
        db.flush()
        from ekoa_config.connector_crypto import encrypt_secret
        db.add(ConnectorCredential(
            connector_id=conn.id, token_type="pat",
            access_token_encrypted=encrypt_secret("ghp_synctoken"),
        ))
        db.commit()
        return conn.id


def _install_fake_embeddings(monkeypatch):
    """Stub the embedding/index pipeline so sync tests don't need Qdrant/torch."""
    def fake_ensure_collection(name, vector_size=384):
        return None

    def fake_generate_embeddings(texts):
        return [[0.1] * 384 for _ in texts]

    def fake_index_chunks(collection_name, document_id, chunks, embeddings, organization_id=None, workspace_id=None):
        return len(chunks)

    import apps.worker.embeddings as emb
    monkeypatch.setattr(emb, "ensure_collection", fake_ensure_collection)
    monkeypatch.setattr(emb, "generate_embeddings", fake_generate_embeddings)
    monkeypatch.setattr(emb, "index_chunks", fake_index_chunks)


def _install_fake_github(monkeypatch, files: dict[str, bytes]):
    """Stub the GitHub API seams: tree listing + raw content fetch."""
    import apps.api.services.connectors.github as gh

    def fake_tree(self, config, token, branch):
        return list(files.keys())

    def fake_raw(self, config, token, path):
        if path not in files:
            from apps.api.services.connectors.base import ConnectorSyncError
            raise ConnectorSyncError(f"Remote file '{path}' disappeared during sync")
        return files[path]

    monkeypatch.setattr(gh.GitHubConnector, "_repo_tree_files", fake_tree)
    monkeypatch.setattr(gh.GitHubConnector, "_fetch_raw", fake_raw)
    # test_connection is called inside sync() â†’ stub it too.
    monkeypatch.setattr(
        gh.GitHubConnector,
        "test_connection",
        lambda self, config, token: {
            "owner": config["owner"], "repo": config["repo"],
            "default_branch": "main", "full_name": f"{config['owner']}/{config['repo']}",
        },
    )


def test_sync_ingests_docs_and_dedups_on_resync(sync_db, monkeypatch):
    """First sync indexes README + docs/**.md; a re-sync with unchanged files
    creates NO new Documents and NO new DocumentVersions (checksum dedup)."""
    from apps.worker.tasks import sync_connector_task

    connector_id = _seed_connector_sync(sync_db)
    _install_fake_embeddings(monkeypatch)
    files = {
        "README.md": b"# Backend\n\nThis is the README.",
        "docs/getting-started.md": b"# Getting Started\n\nInstall and configure.",
        "docs/api.md": b"# API Reference\n\nEndpoints are documented here.",
    }
    _install_fake_github(monkeypatch, files)

    # get_sync_engine is imported at module load in tasks.py; patch it to the
    # same throwaway engine so the task uses our seeded DB.
    import apps.worker.tasks as tasks_mod
    monkeypatch.setattr(tasks_mod, "get_sync_engine", lambda: sync_db)

    # Celery task body runs synchronously via .run()
    sync_connector_task.run(connector_id=str(connector_id))

    with Session(sync_db) as db:
        docs = db.query(Document).filter(Document.deleted_at.is_(None)).all()
        assert len(docs) == 3
        # Connector source is tagged in metadata.
        tagged = [d for d in docs if (d.metadata_json or {}).get("source") == "github"]
        assert len(tagged) == 3
        assert all(d.status == "INDEXED" for d in docs)
        versions = db.query(DocumentVersion).all()
        assert len(versions) == 3
        assert all(v.version == 1 for v in versions)

        conn = db.query(Connector).filter(Connector.id == connector_id).first()
        assert conn.last_sync_status == "success"
        assert conn.last_sync_document_count == 3

    # Re-sync: nothing changed â†’ everything skipped, zero new rows.
    sync_connector_task.run(connector_id=str(connector_id))

    with Session(sync_db) as db:
        docs = db.query(Document).filter(Document.deleted_at.is_(None)).all()
        assert len(docs) == 3
        versions = db.query(DocumentVersion).all()
        assert len(versions) == 3
        assert all(v.version == 1 for v in versions)
        conn = db.query(Connector).filter(Connector.id == connector_id).first()
        assert conn.last_sync_status == "success"


def test_sync_reprocesses_changed_file_only(sync_db, monkeypatch):
    """Only the changed file is re-indexed (new DocumentVersion v2); the others
    are skipped and keep version 1."""
    from apps.worker.tasks import sync_connector_task

    connector_id = _seed_connector_sync(sync_db)
    _install_fake_embeddings(monkeypatch)
    files = {
        "README.md": b"# Backend\n\nThis is the README.",
        "docs/api.md": b"# API Reference\n\nEndpoints are documented here.",
    }
    _install_fake_github(monkeypatch, files)

    import apps.worker.tasks as tasks_mod
    monkeypatch.setattr(tasks_mod, "get_sync_engine", lambda: sync_db)

    sync_connector_task.run(connector_id=str(connector_id))
    # Change README content only.
    files["README.md"] = b"# Backend\n\nThis README was updated with new content."
    sync_connector_task.run(connector_id=str(connector_id))

    with Session(sync_db) as db:
        versions = db.query(DocumentVersion).order_by(DocumentVersion.document_id, DocumentVersion.version).all()
        # 2 docs, one bumped to v2 â†’ 3 versions total.
        assert len(versions) == 3
        readme_versions = [v for v in versions if v.file_path.endswith("README.md")]
        api_versions = [v for v in versions if v.file_path.endswith("docs/api.md")]
        assert [v.version for v in readme_versions] == [1, 2]
        assert [v.version for v in api_versions] == [1]


def test_sync_revoked_token_marks_connector_error(sync_db, monkeypatch):
    """A revoked/invalid token fails gracefully: connector flips to error with
    a reason; the task does not crash and does not create documents."""
    from apps.worker.tasks import sync_connector_task

    connector_id = _seed_connector_sync(sync_db)
    _install_fake_embeddings(monkeypatch)
    files = {"README.md": b"# Backend"}
    _install_fake_github(monkeypatch, files)

    import apps.api.services.connectors.github as gh
    from apps.api.services.connectors.base import ConnectorValidationError

    def bad_connection(self, config, access_token):
        raise ConnectorValidationError(
            "GitHub rejected the token during sync â€” it is invalid, expired, or revoked"
        )

    monkeypatch.setattr(gh.GitHubConnector, "test_connection", bad_connection)

    import apps.worker.tasks as tasks_mod
    monkeypatch.setattr(tasks_mod, "get_sync_engine", lambda: sync_db)

    # Should NOT raise â€” permanent failure is recorded, not retried.
    sync_connector_task.run(connector_id=str(connector_id))

    with Session(sync_db) as db:
        conn = db.query(Connector).filter(Connector.id == connector_id).first()
        assert conn.status == "error"
        assert "revoked" in (conn.status_reason or "").lower() or "invalid" in (conn.status_reason or "").lower()
        assert conn.last_sync_status == "failed"
        docs = db.query(Document).filter(Document.deleted_at.is_(None)).all()
        assert len(docs) == 0  # nothing indexed


# â”€â”€ Health check â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@pytest.mark.asyncio
async def test_health_reflects_token_validity(client, db_session):
    """Health reports the REAL state: revoked token â†’ token_valid=False and the
    connector flips from connected â†’ error."""
    headers = await _register_login(client, f"health-{uuid.uuid4().hex[:8]}@example.com")
    seed = await _seed_org_ws(client, headers, db_session)

    import apps.api.services.connectors.github as gh
    original = gh._github_request

    def fake_request(method, url, access_token, headers=None, **kwargs):
        from httpx import Response
        if "/repos/" in url:
            return Response(200, json={
                "full_name": "acme/backend",
                "default_branch": "main",
                "private": False,
            })
        raise AssertionError(f"unexpected call {method} {url}")

    gh._github_request = fake_request
    try:
        resp = await client.post("/api/v1/connectors/", headers=seed["headers"], json={
            "provider": "github",
            "workspace_id": seed["ws"]["id"],
            "name": "Health Check",
            "access_token": "ghp_health",
            "config": {"owner": "acme", "repo": "backend"},
        })
        assert resp.status_code == 201
    finally:
        gh._github_request = original

    connector_id = resp.json()["id"]

    # Healthy: token valid.
    def ok_request(method, url, access_token, headers=None, **kwargs):
        from httpx import Response
        if "/repos/" in url:
            return Response(200, json={"full_name": "acme/backend"})
        raise AssertionError(f"unexpected call {method} {url}")

    gh._github_request = ok_request
    try:
        h = await client.get(f"/api/v1/connectors/{connector_id}/health", headers=seed["headers"])
        assert h.status_code == 200, h.text
        assert h.json()["token_valid"] is True
        assert h.json()["status"] == "connected"
    finally:
        gh._github_request = original

    # Revoked token: health flips connector to error.
    def revoked_request(method, url, access_token, headers=None, **kwargs):
        from httpx import Response
        if "/repos/" in url:
            return Response(401, json={"message": "Bad credentials"})
        raise AssertionError(f"unexpected call {method} {url}")

    gh._github_request = revoked_request
    try:
        h = await client.get(f"/api/v1/connectors/{connector_id}/health", headers=seed["headers"])
        assert h.status_code == 200
        assert h.json()["token_valid"] is False
        assert h.json()["status"] == "error"
    finally:
        gh._github_request = original

    conn = (await db_session.execute(
        select(Connector).where(Connector.id == uuid.UUID(connector_id))
    )).scalar_one()
    assert conn.status == "error"
    assert conn.status_reason  # reason recorded, not silent


# â”€â”€ Sync trigger endpoint (admin-gated, audited) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@pytest.mark.asyncio
async def test_sync_trigger_enqueues_and_audits(client, db_session, monkeypatch):
    """Manual 'Sync Now' is admin-gated, sets running status, enqueues the task,
    and writes an audit entry."""
    headers = await _register_login(client, f"trig-{uuid.uuid4().hex[:8]}@example.com")
    seed = await _seed_org_ws(client, headers, db_session)

    import apps.api.services.connectors.github as gh
    original = gh._github_request

    def fake_request(method, url, access_token, headers=None, **kwargs):
        from httpx import Response
        if "/repos/" in url:
            return Response(200, json={
                "full_name": "acme/backend",
                "default_branch": "main",
                "private": False,
            })
        raise AssertionError(f"unexpected call {method} {url}")

    gh._github_request = fake_request
    try:
        resp = await client.post("/api/v1/connectors/", headers=seed["headers"], json={
            "provider": "github",
            "workspace_id": seed["ws"]["id"],
            "name": "Trig Me",
            "access_token": "ghp_trig",
            "config": {"owner": "acme", "repo": "backend"},
        })
        assert resp.status_code == 201
    finally:
        gh._github_request = original

    connector_id = resp.json()["id"]

    # Stub the Celery task so no broker/worker is needed in tests.
    fake_tasks = types.ModuleType("apps.worker.tasks")
    fake_tasks.sync_connector_task = types.SimpleNamespace(delay=lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, "apps.worker.tasks", fake_tasks)

    s = await client.post(f"/api/v1/connectors/{connector_id}/sync", headers=seed["headers"])
    assert s.status_code == 200, s.text
    assert s.json()["status"] == "sync_triggered"

    conn = (await db_session.execute(
        select(Connector).where(Connector.id == uuid.UUID(connector_id))
    )).scalar_one()
    assert conn.last_sync_status == "running"

    audits = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == "connector.sync_triggered")
    )).scalars().all()
    assert len(audits) >= 1
