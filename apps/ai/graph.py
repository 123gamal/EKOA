"""LangGraph multi-agent orchestration for EKOA."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal

from langgraph.graph import StateGraph, END
from typing_extensions import TypedDict

from ekoa_config.settings import get_settings

from apps.ai.retriever import retrieve_chunks

settings = get_settings()

logger = logging.getLogger(__name__)


# ── State ────────────────────────────────────────────────────────────────────


class AgentAction(TypedDict):
    tool_name: str
    tool_input: dict[str, Any]
    tool_output: str | None
    timestamp: str


class AgentState(TypedDict):
    messages: list[dict[str, str]]
    actions: list[AgentAction]
    context_chunks: list[dict]
    workspace_id: str
    collection_name: str
    final_answer: str | None
    degraded: bool


# ── Agent Node Implementations ───────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def coordinator_node(state: AgentState) -> dict:
    """Route the user's message and build a final response."""
    user_msg = state["messages"][-1]["content"] if state["messages"] else ""

    action: AgentAction = {
        "tool_name": "coordinator.analyze",
        "tool_input": {"query": user_msg},
        "tool_output": "Analyzing query and routing to appropriate agents",
        "timestamp": _now(),
    }

    return {
        "actions": state["actions"] + [action],
    }


def retriever_node(state: AgentState) -> dict:
    """Query Qdrant vector store for relevant chunks."""
    user_msg = state["messages"][-1]["content"] if state["messages"] else ""

    action_input = {"query": user_msg, "collection": state.get("collection_name", "ekoa_default")}
    try:
        chunks = retrieve_chunks(
            query=user_msg,
            collection_name=state.get("collection_name", "ekoa_default"),
        )
        action_output = f"Retrieved {len(chunks)} relevant chunks from vector store"
    except Exception as e:
        chunks = []
        action_output = f"Retrieval failed: {e}"

    action: AgentAction = {
        "tool_name": "retriever.search",
        "tool_input": action_input,
        "tool_output": action_output,
        "timestamp": _now(),
    }

    return {
        "context_chunks": chunks,
        "actions": state["actions"] + [action],
    }


def document_node(state: AgentState) -> dict:
    """Summarize document context from retrieved chunks."""
    chunks = state.get("context_chunks", [])
    if not chunks:
        doc_summary = "No document context available."
    else:
        source_ids = set(c["document_id"] for c in chunks if c.get("document_id"))
        doc_summary = f"Found relevant content across {len(source_ids)} document(s)"

    action: AgentAction = {
        "tool_name": "document.summarize",
        "tool_input": {"chunk_count": len(chunks), "source_documents": len(source_ids) if chunks else 0},
        "tool_output": doc_summary,
        "timestamp": _now(),
    }

    return {
        "actions": state["actions"] + [action],
    }


def _call_llm(messages: list[dict[str, str]], context: str | None = None) -> tuple[str, bool]:
    """Call the configured LLM provider (deepseek or gemini) with messages and optional context.

    Returns (answer, degraded). ``degraded`` is True only when no real LLM provider
    answered and the local fallback template was used instead.
    """
    user_msg = messages[-1]["content"] if messages else ""

    # Try DeepSeek first
    deepseek_key = settings.DEEPSEEK_API_KEY or settings.LLM_API_KEY
    if deepseek_key and not deepseek_key.startswith("sk-your"):
        try:
            from openai import OpenAI
            client = OpenAI(
                api_key=deepseek_key,
                base_url=settings.DEEPSEEK_BASE_URL,
            )
            system_content = "You are EKOA (Enterprise Knowledge Operations Assistant), an expert AI assistant."
            if context:
                system_content += f"\n\nBase your answer on the following retrieved knowledge base context:\n{context[:10000]}"
            else:
                system_content += "\n\nAnswer the user's query clearly and concisely."
            
            full_messages = [{"role": "system", "content": system_content}] + [
                {"role": m["role"], "content": m["content"]} for m in messages if m.get("content")
            ]
            resp = client.chat.completions.create(
                model=settings.DEEPSEEK_MODEL,
                messages=full_messages,
                temperature=0.3,
                max_tokens=2048,
            )
            if resp.choices[0].message.content:
                return resp.choices[0].message.content.strip(), False
        except Exception as exc:
            logger.warning("DeepSeek LLM call failed (falling back): %s: %s", type(exc).__name__, exc)

    # Try Gemini fallback
    gemini_key = settings.GEMINI_API_KEY
    if gemini_key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_key)
            model = genai.GenerativeModel(settings.GEMINI_MODEL)
            prompt = "You are EKOA (Enterprise Knowledge Operations Assistant)."
            if context:
                prompt += f"\n\nContext:\n{context[:10000]}"
            prompt += f"\n\nUser Question: {user_msg}"
            resp = model.generate_content(prompt)
            if resp.text:
                return resp.text.strip(), False
        except Exception as exc:
            logger.warning("Gemini LLM call failed (falling back): %s: %s", type(exc).__name__, exc)

    return _fallback_answer(messages, context), True


def _fallback_answer(messages: list[dict], context: str | None) -> str:
    """Intelligent fallback answer when external LLM API key is absent or unreachable."""
    user_msg = (messages[-1]["content"] if messages else "").strip()

    if context:
        return (
            f"**Information Found in Workspace Documents:**\n\n"
            f"{context[:800]}\n\n"
            f"*(Note: You can connect a DeepSeek or Gemini API key in settings for expanded natural language generation.)*"
        )

    # Conversational handling for common queries when no document context is indexed yet
    lowered = user_msg.lower()
    if any(greeting in lowered for greeting in ["hi", "hello", "hey", "greetings", "start"]):
        return (
            "Hello! I am **EKOA**, your Enterprise Knowledge Operations Assistant.\n\n"
            "Here is how I can assist you:\n"
            "- 📄 **Document Search**: Upload PDFs, DOCX, TXT, or Markdown files under **Documents**.\n"
            "- 🔍 **RAG Knowledge Base**: Ask me any questions about your uploaded enterprise documents.\n"
            "- ⚡ **Agent Orchestration**: I automatically route questions through Coordinator, Retriever, and Synthesizer agents.\n\n"
            "Select a workspace above or upload a document to get started!"
        )

    return (
        f"I searched the active workspace knowledge base for **'{user_msg}'**, but no matching document content was found.\n\n"
        "**Suggestions:**\n"
        "1. Go to the **Documents** tab and upload relevant files (PDF, DOCX, TXT, Markdown).\n"
        "2. Ensure the correct workspace is selected in the dropdown menu above.\n"
        "3. Rephrase your question or try searching for specific keywords."
    )


def synthesize_node(state: AgentState) -> dict:
    """Synthesize the final answer from all agent outputs and context."""
    user_msg = state["messages"][-1]["content"] if state["messages"] else ""
    chunks = state.get("context_chunks", [])

    context = None
    citations = []
    if chunks:
        context = "\n\n".join(c["text"] for c in chunks if c.get("text"))
        citations = list(set(c["document_id"] for c in chunks if c.get("document_id")))

    answer, degraded = _call_llm(state["messages"], context)

    action: AgentAction = {
        "tool_name": "coordinator.synthesize",
        "tool_input": {"chunks_used": len(chunks), "citations": citations},
        "tool_output": f"Synthesized answer using {len(chunks)} context chunks",
        "timestamp": _now(),
    }

    return {
        "final_answer": answer,
        "degraded": degraded,
        "actions": state["actions"] + [action],
    }


def router_condition(state: AgentState) -> Literal["retriever", "document", "synthesize"]:
    """Decide which agent to call next based on current state."""
    actions = state.get("actions", [])

    if not actions:
        return "retriever"

    has_retrieved = any(a["tool_name"] == "retriever.search" for a in actions)
    has_document = any(a["tool_name"] == "document.summarize" for a in actions)

    if has_retrieved and not has_document:
        return "document"
    if has_document:
        return "synthesize"
    return "retriever"


# ── Build Graph ──────────────────────────────────────────────────────────────


def build_agent_graph() -> StateGraph:
    """Construct the LangGraph agent orchestration graph."""
    workflow = StateGraph(AgentState)

    workflow.add_node("coordinator", coordinator_node)
    workflow.add_node("retriever", retriever_node)
    workflow.add_node("document", document_node)
    workflow.add_node("synthesize", synthesize_node)

    workflow.set_entry_point("coordinator")

    workflow.add_conditional_edges(
        "coordinator",
        router_condition,
        {
            "retriever": "retriever",
            "document": "document",
            "synthesize": "synthesize",
        },
    )
    workflow.add_edge("retriever", "document")
    workflow.add_edge("document", "synthesize")
    workflow.add_edge("synthesize", END)

    return workflow.compile()


# Compiled graph instance (lazily initialized)
_graph_instance: StateGraph | None = None


def get_agent_graph() -> StateGraph:
    global _graph_instance
    if _graph_instance is None:
        _graph_instance = build_agent_graph()
    return _graph_instance
