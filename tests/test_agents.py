"""Tests for the LangGraph multi-agent orchestration graph — full edge case coverage."""

import pytest
from apps.ai.graph import build_agent_graph, AgentState


@pytest.mark.asyncio
async def test_agent_graph_initial_state():
    graph = build_agent_graph()

    state: AgentState = {
        "messages": [{"role": "user", "content": "Find information about project X"}],
        "actions": [],
        "context_chunks": [],
        "workspace_id": "test-workspace",
        "collection_name": "ekoa_test",
        "final_answer": None,
    }

    result = await graph.ainvoke(state)

    assert result is not None
    assert "final_answer" in result
    assert result["final_answer"] is not None
    assert len(result["final_answer"]) > 0
    assert "actions" in result
    assert len(result["actions"]) > 0


@pytest.mark.asyncio
async def test_agent_graph_routing():
    graph = build_agent_graph()

    state: AgentState = {
        "messages": [{"role": "user", "content": "What is the capital of France?"}],
        "actions": [],
        "context_chunks": [],
        "workspace_id": "test-workspace",
        "collection_name": "ekoa_test",
        "final_answer": None,
    }

    result = await graph.ainvoke(state)
    actions = result.get("actions", [])

    action_names = [a["tool_name"] for a in actions]
    assert "coordinator.analyze" in action_names
    assert "retriever.search" in action_names
    assert "document.summarize" in action_names
    assert "coordinator.synthesize" in action_names


@pytest.mark.asyncio
async def test_agent_graph_empty_messages():
    graph = build_agent_graph()

    state: AgentState = {
        "messages": [],
        "actions": [],
        "context_chunks": [],
        "workspace_id": "",
        "collection_name": "ekoa_default",
        "final_answer": None,
    }

    result = await graph.ainvoke(state)
    assert result["final_answer"] is not None
    assert len(result["actions"]) > 0


@pytest.mark.asyncio
async def test_agent_graph_missing_workspace():
    graph = build_agent_graph()

    state: AgentState = {
        "messages": [{"role": "user", "content": "Hello"}],
        "actions": [],
        "context_chunks": [],
        "workspace_id": "",
        "collection_name": "ekoa_default",
        "final_answer": None,
    }

    result = await graph.ainvoke(state)
    assert result is not None
    assert result["final_answer"] is not None


@pytest.mark.asyncio
async def test_agent_graph_missing_collection():
    graph = build_agent_graph()

    state: AgentState = {
        "messages": [{"role": "user", "content": "Hello"}],
        "actions": [],
        "context_chunks": [],
        "workspace_id": "test",
        "collection_name": "",
        "final_answer": None,
    }

    result = await graph.ainvoke(state)
    assert result["final_answer"] is not None


@pytest.mark.asyncio
async def test_agent_graph_nonexistent_collection():
    graph = build_agent_graph()

    state: AgentState = {
        "messages": [{"role": "user", "content": "Tell me about something"}],
        "actions": [],
        "context_chunks": [],
        "workspace_id": "test",
        "collection_name": "non_existent_collection_xyz",
        "final_answer": None,
    }

    result = await graph.ainvoke(state)
    assert result is not None
    assert result["final_answer"] is not None
    # Should gracefully handle no results
    assert "couldn't find" in result["final_answer"].lower() or len(result.get("context_chunks", [])) == 0


@pytest.mark.asyncio
async def test_agent_graph_very_long_message():
    graph = build_agent_graph()

    long_content = "word " * 50000
    state: AgentState = {
        "messages": [{"role": "user", "content": long_content}],
        "actions": [],
        "context_chunks": [],
        "workspace_id": "test",
        "collection_name": "ekoa_test",
        "final_answer": None,
    }

    result = await graph.ainvoke(state)
    assert result is not None
    assert result["final_answer"] is not None


@pytest.mark.asyncio
async def test_agent_graph_special_characters():
    graph = build_agent_graph()

    state: AgentState = {
        "messages": [{"role": "user", "content": "!@#$%^&*()_+{}|:\"<>?~`-=[]\\;',./\n\t"}],
        "actions": [],
        "context_chunks": [],
        "workspace_id": "test",
        "collection_name": "ekoa_test",
        "final_answer": None,
    }

    result = await graph.ainvoke(state)
    assert result is not None
    assert result["final_answer"] is not None


@pytest.mark.asyncio
async def test_agent_graph_unicode_message():
    graph = build_agent_graph()

    state: AgentState = {
        "messages": [{"role": "user", "content": "你好世界! 🌍 ¿Qué tal? こんにちは ✅"}],
        "actions": [],
        "context_chunks": [],
        "workspace_id": "test",
        "collection_name": "ekoa_test",
        "final_answer": None,
    }

    result = await graph.ainvoke(state)
    assert result is not None
    assert result["final_answer"] is not None


@pytest.mark.asyncio
async def test_agent_graph_multiple_messages():
    graph = build_agent_graph()

    state: AgentState = {
        "messages": [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi! How can I help?"},
            {"role": "user", "content": "Tell me about EKOA"},
        ],
        "actions": [],
        "context_chunks": [],
        "workspace_id": "test",
        "collection_name": "ekoa_test",
        "final_answer": None,
    }

    result = await graph.ainvoke(state)
    assert result is not None
    assert result["final_answer"] is not None


@pytest.mark.asyncio
async def test_agent_graph_whitespace_message():
    graph = build_agent_graph()

    state: AgentState = {
        "messages": [{"role": "user", "content": "   \n\n   \t   "}],
        "actions": [],
        "context_chunks": [],
        "workspace_id": "test",
        "collection_name": "ekoa_test",
        "final_answer": None,
    }

    result = await graph.ainvoke(state)
    assert result is not None
    assert result["final_answer"] is not None


@pytest.mark.asyncio
async def test_graph_compilation():
    graph = build_agent_graph()
    assert graph is not None

    for node_name in ("coordinator", "retriever", "document", "synthesize"):
        assert node_name in graph.nodes


@pytest.mark.asyncio
async def test_agent_graph_not_degraded_when_llm_answers(monkeypatch):
    """A real LLM answer must propagate degraded=False through the graph."""
    import apps.ai.graph as graph_mod

    monkeypatch.setattr(
        graph_mod, "_call_llm",
        lambda messages, context=None: (
            "real answer", False, {"provider": "deepseek", "model": "deepseek-chat"},
        ),
    )

    state: AgentState = {
        "messages": [{"role": "user", "content": "Hello"}],
        "actions": [],
        "context_chunks": [],
        "workspace_id": "test",
        "collection_name": "ekoa_test",
        "final_answer": None,
    }
    result = await graph_mod.build_agent_graph().ainvoke(state)
    assert result["final_answer"] == "real answer"
    assert result["degraded"] is False
    assert result["llm_telemetry"]["provider"] == "deepseek"


@pytest.mark.asyncio
async def test_agent_graph_degraded_flag_when_llm_unavailable(monkeypatch):
    """When _call_llm falls back to templates, degraded must be True."""
    import apps.ai.graph as graph_mod

    monkeypatch.setattr(
        graph_mod, "_call_llm",
        lambda messages, context=None: (
            "template fallback", True,
            {"provider": None, "model": None, "latency_ms": None},
        ),
    )

    state: AgentState = {
        "messages": [{"role": "user", "content": "Hello"}],
        "actions": [],
        "context_chunks": [],
        "workspace_id": "test",
        "collection_name": "ekoa_test",
        "final_answer": None,
    }
    result = await graph_mod.build_agent_graph().ainvoke(state)
    assert result["final_answer"] == "template fallback"
    assert result["degraded"] is True
