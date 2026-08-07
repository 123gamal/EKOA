"""Security hardening tests: CORS, rate limiting, RBAC, refresh-token cookie.

These exercise Phase 3 controls against the same in-memory ASGI test app used
by the rest of the suite. The process-wide rate limiter is reset by the
autouse ``reset_rate_limiter`` fixture in conftest.py so buckets do not bleed
between tests.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from apps.api.models.user import User
from apps.api.models.org_member import OrgMember
from ekoa_config.rate_limit import RateLimiter
from ekoa_config.settings import Settings, resolve_cors_origins

pytestmark = pytest.mark.asyncio


# ── CORS ─────────────────────────────────────────────────────────────────────

async def test_resolve_cors_origins_safe_default():
    """An explicit origins list is returned as-is."""
    settings = Settings(CORS_ORIGINS='["http://localhost:3000"]')
    assert resolve_cors_origins(settings) == ["http://localhost:3000"]


async def test_resolve_cors_origins_rejects_wildcard_with_credentials():
    """Wildcard + allow_credentials=True must fail loudly, not silently break."""
    settings = Settings(CORS_ORIGINS='["*"]')
    with pytest.raises(RuntimeError):
        resolve_cors_origins(settings, allow_credentials=True)


async def test_resolve_cors_origins_rejects_invalid_json():
    """Non-JSON CORS_ORIGINS raises at startup."""
    settings = Settings(CORS_ORIGINS="not-json")
    with pytest.raises(RuntimeError):
        resolve_cors_origins(settings)


async def test_resolve_cors_origins_rejects_non_string_list():
    """A JSON array that is not a list of strings is rejected."""
    settings = Settings(CORS_ORIGINS='["http://localhost:3000", 42]')
    with pytest.raises(RuntimeError):
        resolve_cors_origins(settings)


async def test_cors_header_present_for_allowed_origin(client: AsyncClient):
    resp = await client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"


async def test_cors_header_absent_for_disallowed_origin(client: AsyncClient):
    resp = await client.get("/health", headers={"Origin": "http://evil.example.com"})
    assert "access-control-allow-origin" not in resp.headers


async def test_cors_preflight_allowed(client: AsyncClient):
    resp = await client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"


# ── Rate limiting ────────────────────────────────────────────────────────────

async def test_rate_limiter_sliding_window_unit():
    """RateLimiter rejects over-limit clients and keeps other keys independent."""
    limiter = RateLimiter()
    try:
        for _ in range(5):
            assert limiter.check("s", "k", 5, 60)[0] is True
        allowed, retry_after = limiter.check("s", "k", 5, 60)
        assert allowed is False
        assert retry_after >= 1
        assert limiter.check("s", "other", 5, 60)[0] is True
    finally:
        limiter.reset()


async def test_login_rate_limit_returns_429_with_retry_after(client: AsyncClient):
    """Login attempts beyond the per-IP limit return 429 + Retry-After."""
    await client.post("/api/v1/auth/register", json={
        "email": "rl@example.com", "password": "strong1234567", "full_name": "RL",
    })
    for _ in range(10):
        resp = await client.post("/api/v1/auth/login", json={
            "email": "rl@example.com", "password": "wrong-password",
        })
        assert resp.status_code == 401

    resp = await client.post("/api/v1/auth/login", json={
        "email": "rl@example.com", "password": "wrong-password",
    })
    assert resp.status_code == 429
    assert resp.headers.get("retry-after") is not None
    assert int(resp.headers["retry-after"]) >= 1


async def test_general_rate_limit_exempts_health(client: AsyncClient):
    """/health must never be rate-limited (Docker healthchecks)."""
    for _ in range(5):
        resp = await client.get("/health")
        assert resp.status_code == 200


# ── RBAC ─────────────────────────────────────────────────────────────────────

async def _register_login(client: AsyncClient, email: str, password: str = "strong1234567"):
    await client.post("/api/v1/auth/register", json={
        "email": email, "password": password, "full_name": "T",
    })
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _set_member_role(db, email: str, org_id, role: str) -> None:
    """Insert or update an OrgMember row directly (no invite flow exists yet)."""
    user = await db.scalar(select(User).where(User.email == email))
    org_uuid = uuid.UUID(org_id)
    member = await db.scalar(
        select(OrgMember).where(
            OrgMember.organization_id == org_uuid, OrgMember.user_id == user.id
        )
    )
    if member is None:
        db.add(OrgMember(organization_id=org_uuid, user_id=user.id, role=role))
    else:
        member.role = role
    await db.commit()


async def test_rbac_hierarchy_unknown_role_is_rejected(client: AsyncClient, db_session):
    """assert_min_role rejects unknown role strings (owner > admin > member)."""
    from apps.api.dependencies.authz import assert_min_role

    ha = await _register_login(client, "rbac-hierarchy@example.com")
    org = (await client.post("/api/v1/organizations/", json={
        "name": "Acme", "slug": "acme-unknown",
    }, headers=ha)).json()

    # Owner role lets an owner clear an admin gate
    user = await db_session.scalar(select(User).where(User.email == "rbac-hierarchy@example.com"))
    await assert_min_role(db_session, user.id, uuid.UUID(org["id"]), "admin")
    with pytest.raises(ValueError):
        await assert_min_role(db_session, user.id, uuid.UUID(org["id"]), "superadmin")


async def test_rbac_role_hierarchy_gates_sensitive_routes(client: AsyncClient, db_session):
    """member cannot create workspaces/workflows or trigger runs; admin can.

    The run route rejects a low-role user (403) before reaching the worker
    enqueue import, so the route-level negative case is asserted directly; the
    positive (admin) case is proven via assert_min_role and via the admin-only
    create routes, avoiding the slow langchain worker import in the test env.
    """
    ha = await _register_login(client, "rbac-owner@example.com")
    org = (await client.post("/api/v1/organizations/", json={
        "name": "Acme", "slug": "acme-rbac",
    }, headers=ha)).json()
    ws = (await client.post("/api/v1/workspaces/", json={
        "name": "Eng", "organization_id": org["id"],
    }, headers=ha)).json()

    hb = await _register_login(client, "rbac-member@example.com")

    # Not a member yet -> membership check rejects
    resp = await client.post("/api/v1/workspaces/", json={
        "name": "X", "organization_id": org["id"],
    }, headers=hb)
    assert resp.status_code == 403

    # Join as a plain member -> admin-gated routes still 403
    await _set_member_role(db_session, "rbac-member@example.com", org["id"], "member")
    resp = await client.post("/api/v1/workspaces/", json={
        "name": "X", "organization_id": org["id"],
    }, headers=hb)
    assert resp.status_code == 403
    resp = await client.post("/api/v1/workflows/", json={
        "name": "W", "template_id": "doc-ingest-rag", "workspace_id": ws["id"],
    }, headers=hb)
    assert resp.status_code == 403

    # Promote to admin -> create + run gated routes are now allowed
    await _set_member_role(db_session, "rbac-member@example.com", org["id"], "admin")
    resp = await client.post("/api/v1/workspaces/", json={
        "name": "X", "organization_id": org["id"],
    }, headers=hb)
    assert resp.status_code == 201
    wf = (await client.post("/api/v1/workflows/", json={
        "name": "W", "template_id": "doc-ingest-rag", "workspace_id": ws["id"],
    }, headers=hb)).json()

    from apps.api.dependencies.authz import assert_min_role

    member_user = await db_session.scalar(
        select(User).where(User.email == "rbac-member@example.com")
    )
    await assert_min_role(db_session, member_user.id, uuid.UUID(org["id"]), "admin")

    # Demote to member -> run is forbidden again (route-level, before worker import)
    await _set_member_role(db_session, "rbac-member@example.com", org["id"], "member")
    resp = await client.post(f"/api/v1/workflows/{wf['id']}/run", json={}, headers=hb)
    assert resp.status_code == 403


# ── Refresh-token cookie ─────────────────────────────────────────────────────

async def test_login_sets_httponly_refresh_cookie(client: AsyncClient):
    """Login delivers the refresh token as an HttpOnly cookie, not readable by JS."""
    await client.post("/api/v1/auth/register", json={
        "email": "cookie@example.com", "password": "strong1234567", "full_name": "C",
    })
    resp = await client.post("/api/v1/auth/login", json={
        "email": "cookie@example.com", "password": "strong1234567",
    })
    assert resp.status_code == 200
    assert "refresh_token" in resp.cookies

    set_cookie = resp.headers.get("set-cookie", "")
    assert "refresh_token=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    # Development environment must NOT set Secure (would break http://localhost)
    assert "Secure" not in set_cookie


async def test_refresh_uses_httponly_cookie_and_rotates(client: AsyncClient):
    """A cookie-authenticated refresh rotates the token without a body token."""
    await client.post("/api/v1/auth/register", json={
        "email": "rotate@example.com", "password": "strong1234567", "full_name": "R",
    })
    login = await client.post("/api/v1/auth/login", json={
        "email": "rotate@example.com", "password": "strong1234567",
    })
    assert login.status_code == 200
    old_refresh = login.cookies.get("refresh_token")

    # No body token; the cookie must be enough.
    resp = await client.post("/api/v1/auth/refresh", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert "refresh_token" in resp.cookies
    assert resp.cookies.get("refresh_token") != old_refresh  # rotated


async def test_logout_clears_refresh_cookie_and_revokes(client: AsyncClient):
    """Logout clears the HttpOnly cookie and revokes the session server-side."""
    await client.post("/api/v1/auth/register", json={
        "email": "bye@example.com", "password": "strong1234567", "full_name": "B",
    })
    login = await client.post("/api/v1/auth/login", json={
        "email": "bye@example.com", "password": "strong1234567",
    })
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    old_refresh = login.cookies.get("refresh_token")

    resp = await client.post("/api/v1/auth/logout", json={}, headers=headers)
    assert resp.status_code == 204
    # Cookie cleared (expired)
    set_cookie = resp.headers.get("set-cookie", "")
    assert "refresh_token=" in set_cookie
    assert "Max-Age=0" in set_cookie or "expires" in set_cookie.lower()

    # The revoked token can no longer refresh (401 via the session-revocation check).
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert resp.status_code == 401
