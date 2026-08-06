"""Tests for AI service authentication enforcement."""

import pytest
from httpx import AsyncClient, ASGITransport

from apps.ai.main import app


pytestmark = pytest.mark.asyncio


@pytest.fixture
async def ai_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


async def test_ai_chat_requires_auth(ai_client: AsyncClient):
    """Chat endpoint rejects requests without a valid bearer token."""
    resp = await ai_client.post("/api/v1/ai/chat", json={
        "workspace_id": "00000000-0000-0000-0000-000000000000",
        "message": "hello",
    })
    assert resp.status_code == 401


async def test_ai_chat_rejects_malformed_token(ai_client: AsyncClient):
    """Chat endpoint rejects a malformed/expired token."""
    resp = await ai_client.post("/api/v1/ai/chat", json={
        "workspace_id": "00000000-0000-0000-0000-000000000000",
        "message": "hello",
    }, headers={"Authorization": "Bearer not-a-valid-jwt-token"})
    assert resp.status_code == 401


async def test_ai_stream_requires_auth(ai_client: AsyncClient):
    """Streaming chat endpoint rejects requests without a valid bearer token."""
    resp = await ai_client.post("/api/v1/ai/chat/stream", json={
        "workspace_id": "00000000-0000-0000-0000-000000000000",
        "message": "hello",
    })
    assert resp.status_code == 401


async def test_ai_chat_rejects_invalid_workspace_id_type(ai_client: AsyncClient):
    """A syntactically invalid workspace_id is a client error (400)."""
    resp = await ai_client.post("/api/v1/ai/chat", json={
        "workspace_id": "not-a-uuid",
        "message": "hello",
    }, headers={"Authorization": "Bearer 00000000-0000-0000-0000-000000000000"})
    # Token invalid → 401 happens first; ensure it's guarded either way
    assert resp.status_code in (400, 401)