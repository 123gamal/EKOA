"""Phase 16 Part B tests: Analytics/Research agent nodes + QA self-check.

Same fast/deterministic node-level testing style as tests/test_phase15.py —
mocked/controlled inputs, not live LLM calls. Live routing/verification
happens separately against the running Docker stack.
"""

from __future__ import annotations

import uuid

import pytest

from apps.ai.graph import (
    MAX_RESEARCH_PASSES,
    AgentState,
    _qa_self_check,
    _should_refine_query,
    analytics_node,
    intent_router_condition,
    research_node,
)
from tests.conftest import async_session_factory as conftest_session_factory


def _base_state(**overrides) -> AgentState:
    state: AgentState = {
        "messages": [],
        "actions": [],
        "context_chunks": [],
        "workspace_id": "test-ws",
        "organization_id": None,
        "collection_name": "ekoa_test",
        "final_answer": None,
        "degraded": False,
        "guardrail_flags": [],
        "citations": [],
        "citations_unverified": False,
        "llm_telemetry": {},
        "retrieval_latency_ms": None,
        "intent": None,
        "conversation_summary": None,
        "qa_flags": [],
    }
    state.update(overrides)
    return state


# ── Intent routing (new branches) ───────────────────────────────────────────


def test_intent_router_routes_analytics_and_research():
    assert intent_router_condition(_base_state(intent="analytics")) == "analytics"
    assert intent_router_condition(_base_state(intent="research")) == "research"


# ── Analytics node ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_analytics_node_reports_usage_from_real_db(monkeypatch, db_session):
    """analytics_node reads Document/AiCallLog via the async engine (same
    pattern as workflow_node) and produces a conversational summary."""
    import apps.api.db.engine as engine_mod
    from apps.api.models.document import Document
    from apps.api.models.ai_call_log import AiCallLog
    from apps.api.models.user import User
    from apps.api.models.organization import Organization
    from apps.api.models.workspace import Workspace

    monkeypatch.setattr(engine_mod, "get_session_factory", lambda: conftest_session_factory)

    user = User(email=f"an-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name="U")
    db_session.add(user)
    await db_session.flush()
    org = Organization(name="Analytics Org", slug=f"an-{uuid.uuid4().hex[:8]}", owner_id=user.id)
    db_session.add(org)
    await db_session.flush()
    ws = Workspace(name="Analytics WS", organization_id=org.id, created_by=user.id)
    db_session.add(ws)
    await db_session.flush()

    db_session.add(Document(
        title="Doc", content_type="text/plain", status="INDEXED",
        file_path="d.txt", chunk_count=1, workspace_id=ws.id, uploaded_by=user.id,
    ))
    db_session.add(AiCallLog(
        organization_id=org.id, workspace_id=ws.id, provider="deepseek", model="deepseek-chat",
        latency_ms=200, prompt_tokens=10, completion_tokens=5, total_tokens=15, cost_estimate=0.0001,
    ))
    await db_session.commit()

    state = _base_state(workspace_id=str(ws.id))
    result = await analytics_node(state)

    assert "usage summary" in result["final_answer"].lower()
    assert "1 total" in result["final_answer"] or "Documents" in result["final_answer"]
    assert result["actions"][-1]["tool_name"] == "analytics.summary"


@pytest.mark.asyncio
async def test_analytics_node_handles_invalid_workspace():
    result = await analytics_node(_base_state(workspace_id=""))
    assert "don't have a workspace" in result["final_answer"]


# ── Research node ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_research_node_bounded_to_max_passes(monkeypatch):
    """Even if the refine-check always says "yes, search again", the node
    never exceeds MAX_RESEARCH_PASSES retrieval calls."""
    import apps.ai.graph as graph_mod

    call_count = {"n": 0}

    def fake_retrieve(query, collection_name=None, organization_id=None, workspace_id=None, **kw):
        call_count["n"] += 1
        return [{"document_id": f"doc-{call_count['n']}", "chunk_index": 0, "text": f"chunk from pass {call_count['n']}"}]

    monkeypatch.setattr(graph_mod, "retrieve_chunks", fake_retrieve)
    monkeypatch.setattr(graph_mod, "_should_refine_query", lambda *a, **k: "a narrower query")

    state = _base_state(messages=[{"role": "user", "content": "compare X and Y across all docs"}])
    result = await research_node(state)

    assert call_count["n"] == MAX_RESEARCH_PASSES
    assert len(result["context_chunks"]) == MAX_RESEARCH_PASSES
    assert result["actions"][-1]["tool_input"]["passes"] == MAX_RESEARCH_PASSES


@pytest.mark.asyncio
async def test_research_node_stops_early_when_no_refinement_needed(monkeypatch):
    import apps.ai.graph as graph_mod

    monkeypatch.setattr(
        graph_mod, "retrieve_chunks",
        lambda *a, **k: [{"document_id": "doc-1", "chunk_index": 0, "text": "answer here"}],
    )
    monkeypatch.setattr(graph_mod, "_should_refine_query", lambda *a, **k: None)

    state = _base_state(messages=[{"role": "user", "content": "simple question"}])
    result = await research_node(state)

    assert result["actions"][-1]["tool_input"]["passes"] == 1
    assert len(result["context_chunks"]) == 1


@pytest.mark.asyncio
async def test_research_node_dedupes_merged_chunks(monkeypatch):
    """Chunks with the same (document_id, chunk_index) seen across passes are
    merged, not duplicated."""
    import apps.ai.graph as graph_mod

    responses = [
        [{"document_id": "doc-1", "chunk_index": 0, "text": "a"}],
        [{"document_id": "doc-1", "chunk_index": 0, "text": "a"}, {"document_id": "doc-2", "chunk_index": 0, "text": "b"}],
    ]

    def fake_retrieve(*a, **k):
        return responses.pop(0) if responses else []

    monkeypatch.setattr(graph_mod, "retrieve_chunks", fake_retrieve)
    refine_calls = {"n": 0}

    def fake_refine(*a, **k):
        refine_calls["n"] += 1
        return "follow up" if refine_calls["n"] == 1 else None

    monkeypatch.setattr(graph_mod, "_should_refine_query", fake_refine)

    state = _base_state(messages=[{"role": "user", "content": "multi part question"}])
    result = await research_node(state)

    ids = sorted((c["document_id"], c["chunk_index"]) for c in result["context_chunks"])
    assert ids == [("doc-1", 0), ("doc-2", 0)]


def test_should_refine_query_returns_none_without_context():
    assert _should_refine_query("anything", []) is None


def test_should_refine_query_returns_none_without_llm_configured(monkeypatch):
    from ekoa_config.settings import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", "")
    monkeypatch.setattr(settings, "LLM_API_KEY", "")
    assert _should_refine_query("q", [{"text": "x"}]) is None


# ── QA self-check ────────────────────────────────────────────────────────────


def test_qa_self_check_returns_empty_without_context():
    assert _qa_self_check("some answer", None) == []
    assert _qa_self_check("", "some context") == []


def test_qa_self_check_returns_empty_without_llm_configured(monkeypatch):
    from ekoa_config.settings import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", "")
    monkeypatch.setattr(settings, "LLM_API_KEY", "")
    assert _qa_self_check("answer", "context") == []
