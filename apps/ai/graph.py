"""LangGraph multi-agent orchestration for EKOA."""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any, Literal

from langgraph.graph import StateGraph, END
from typing_extensions import TypedDict

from ekoa_config.settings import get_settings
from ekoa_config.logging import get_logger

from apps.ai.retriever import retrieve_chunks

settings = get_settings()

logger = get_logger("ai.graph")
llm_logger = get_logger("ai.llm")


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
    organization_id: str | None
    collection_name: str
    final_answer: str | None
    degraded: bool
    guardrail_flags: list[dict]
    citations: list[str]
    citations_unverified: bool
    llm_telemetry: dict


# ── Agent Node Implementations ───────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Input guardrails (heuristic) ─────────────────────────────────────────────


# Instruction-override / prompt-injection phrases. These are deliberately
# simple substring patterns; see check_input_guardrails for the honest caveat.
INSTRUCTION_OVERRIDE_PATTERNS: list[str] = [
    r"ignore (all |the )?(previous|prior|above|earlier) (instructions?|prompts?|messages|context|system)",
    r"disregard (all |the )?(previous|prior|above|earlier) (instructions?|prompts?|messages|context|system)",
    r"forget (all |your |the )?(instructions?|prompts?|context|guidelines|rules)",
    r"you are now (unfiltered|uncensored|jailbroken|a? ?dan)",
    r"act as (an? )?(unfiltered|uncensored|jailbroken|dan)",
    r"reveal (your|the) (system prompt|system instructions|inner prompt|hidden prompt)",
    r"(show|print|leak|expose|give me) (your|the) (system|initial|base) prompt",
    r"do not follow (your|the|any) (instructions|prompt|rules)",
    r"override (your |the )?(instructions|prompt|rules)",
    r"jailbreak",
    r"you('re| are) free(d)? from (all )?(rules|constraints|instructions)",
]

# Suspiciously long input: ordinary chat messages are short; anything past this
# is out of distribution and worth flagging.
MAX_MESSAGE_LEN = 4000
# A run of non-alphanumeric characters longer than this is anomalous.
SPECIAL_CHAR_RUN_LEN = 12


def check_input_guardrails(text: str) -> list[dict]:
    """Heuristic prompt-injection / abuse checks on an incoming user message.

    Returns a list of flag dicts (empty when the message looks clean).

    Honest assessment of coverage:
    - Catches obvious instruction-override phrasing ("ignore previous
      instructions", "reveal your system prompt", "jailbreak", ...), long
      runs of special characters, and abnormally long inputs.
    - Will NOT catch novel obfuscated injections, encodings, or subtle
      social-engineering that avoids these literal patterns. This is a cheap
      first-pass tripwire for investigation, NOT a security boundary.
    """
    if not text:
        return []
    lowered = text.lower()
    flags: list[dict] = []

    for pattern in INSTRUCTION_OVERRIDE_PATTERNS:
        if re.search(pattern, lowered):
            flags.append({"type": "instruction_override", "detail": f"matched pattern: {pattern}"})
            break

    longest_run = 0
    for run in re.finditer(r"[^\w\s]+", text):
        longest_run = max(longest_run, len(run.group()))
    if longest_run > SPECIAL_CHAR_RUN_LEN:
        flags.append({
            "type": "excessive_special_characters",
            "detail": f"special-character run of length {longest_run}",
        })

    if len(text) > MAX_MESSAGE_LEN:
        flags.append({
            "type": "excessive_length",
            "detail": f"message length {len(text)} exceeds {MAX_MESSAGE_LEN}",
        })

    return flags


def coordinator_node(state: AgentState) -> dict:
    """Route the user's message, applying input guardrails first.

    Guardrails are flag-and-continue for this phase: a flagged message is
    logged (structured) and carried in state so downstream visibility (audit
    log) can record it, but it is not blocked outright. Blocking on heuristics
    would produce false positives on legitimate long/technical messages.
    """
    user_msg = state["messages"][-1]["content"] if state["messages"] else ""

    flags = check_input_guardrails(user_msg)
    if flags:
        for flag in flags:
            logger.warning(
                "ai.guardrail_triggered",
                extra={
                    "reason": flag["type"],
                    "detail": flag.get("detail"),
                    "workspace_id": state.get("workspace_id"),
                    "organization_id": state.get("organization_id"),
                    "message_preview": user_msg[:120],
                },
            )

    action: AgentAction = {
        "tool_name": "coordinator.analyze",
        "tool_input": {"query": user_msg},
        "tool_output": "Analyzing query and routing to appropriate agents",
        "timestamp": _now(),
    }

    return {
        "guardrail_flags": flags,
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
            organization_id=state.get("organization_id"),
            workspace_id=state.get("workspace_id"),
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


def _call_llm(messages: list[dict[str, str]], context: str | None = None) -> tuple[str, bool, dict]:
    """Call the configured LLM provider (deepseek or gemini) with messages and optional context.

    Returns ``(answer, degraded, telemetry)``. ``degraded`` is True only when
    no real LLM provider answered and the local fallback template was used
    instead. ``telemetry`` carries provider, model, latency in ms, and token
    counts (null when the provider SDK does not report them), which the caller
    persists to ``AiCallLog``.

    Emits structured telemetry per call (unchanged Phase 2 behaviour) that
    mirrors the returned dict.
    """
    user_msg = messages[-1]["content"] if messages else ""

    # Try DeepSeek first
    deepseek_key = settings.DEEPSEEK_API_KEY or settings.LLM_API_KEY
    if deepseek_key and not deepseek_key.startswith("sk-your"):
        start = time.perf_counter()
        try:
            from openai import OpenAI
            client = OpenAI(
                api_key=deepseek_key,
                base_url=settings.DEEPSEEK_BASE_URL,
            )
            system_content = "You are EKOA (Enterprise Knowledge Operations Assistant), an expert AI assistant."
            if context:
                system_content += f"\n\nBase your answer on the following retrieved knowledge base context:\n{context[:10000]}"
                system_content += (
                    "\n\nAt the end of your answer include a single line formatted exactly as: "
                    "CITATIONS: [<document_id>, <document_id>] listing ONLY the document IDs of the "
                    "sources you actually used from the context above. If you used no sources, write "
                    "CITATIONS: []."
                )
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
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
            usage = getattr(resp, "usage", None)
            telemetry = {
                "provider": "deepseek",
                "model": settings.DEEPSEEK_MODEL,
                "latency_ms": elapsed_ms,
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "completion_tokens": getattr(usage, "completion_tokens", None),
                "total_tokens": getattr(usage, "total_tokens", None),
            }
            llm_logger.info(
                "llm_call",
                extra=telemetry,
            )
            if resp.choices[0].message.content:
                return resp.choices[0].message.content.strip(), False, telemetry
        except Exception as exc:
            llm_logger.warning(
                "llm_call_failed",
                extra={"provider": "deepseek", "model": settings.DEEPSEEK_MODEL, "error": f"{type(exc).__name__}: {exc}"},
            )

    # Try Gemini fallback
    gemini_key = settings.GEMINI_API_KEY
    if gemini_key:
        start = time.perf_counter()
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_key)
            model = genai.GenerativeModel(settings.GEMINI_MODEL)
            prompt = "You are EKOA (Enterprise Knowledge Operations Assistant)."
            if context:
                prompt += f"\n\nContext:\n{context[:10000]}"
                prompt += (
                    "\n\nAt the end of your answer include a single line formatted exactly as: "
                    "CITATIONS: [<document_id>, <document_id>] listing ONLY the document IDs of the "
                    "sources you actually used from the context above. If you used no sources, write "
                    "CITATIONS: []."
                )
            prompt += f"\n\nUser Question: {user_msg}"
            resp = model.generate_content(prompt)
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
            usage = getattr(resp, "usage_metadata", None)
            telemetry = {
                "provider": "gemini",
                "model": settings.GEMINI_MODEL,
                "latency_ms": elapsed_ms,
                "prompt_tokens": getattr(usage, "prompt_token_count", None),
                "completion_tokens": getattr(usage, "candidates_token_count", None),
                "total_tokens": getattr(usage, "total_token_count", None),
            }
            llm_logger.info(
                "llm_call",
                extra=telemetry,
            )
            if resp.text:
                return resp.text.strip(), False, telemetry
        except Exception as exc:
            llm_logger.warning(
                "llm_call_failed",
                extra={"provider": "gemini", "model": settings.GEMINI_MODEL, "error": f"{type(exc).__name__}: {exc}"},
            )

    llm_logger.warning("llm_fallback_used", extra={"reason": "no_provider_answered"})
    return _fallback_answer(messages, context), True, {
        "provider": None,
        "model": None,
        "latency_ms": None,
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
    }


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


# ── Citation integrity check ─────────────────────────────────────────────────

_CITATIONS_RE = re.compile(r"CITATIONS:\s*\[([^\]]*)\]", re.IGNORECASE)
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def _extract_citations(answer: str) -> list[str]:
    """Pull the document IDs the model explicitly claimed to cite.

    The model is instructed to close its answer with a ``CITATIONS: [..]``
    line; this parses that line. Returns [] when no explicit claims were made
    (in which case nothing is being asserted, so there is nothing to verify).
    """
    if not answer:
        return []
    match = _CITATIONS_RE.search(answer)
    if not match:
        return []
    tokens = _UUID_RE.findall(match.group(1))
    return list(dict.fromkeys(tokens))


def _strip_citation_line(answer: str) -> str:
    """Remove the machine-readable citations line before the answer is shown."""
    stripped = _CITATIONS_RE.sub("", answer)
    return stripped.replace("\n\n\n", "\n\n").strip()


def validate_citations(citations: list[str], context_chunks: list[dict]) -> tuple[list[str], list[str]]:
    """Cross-check model-cited document IDs against chunks actually retrieved.

    Returns ``(verified, dropped)``. A citation is verified only when its
    document ID appears in the payload of a chunk that was really retrieved
    for this query. This is a deterministic integrity check — not a heuristic.
    """
    retrieved = {c.get("document_id") for c in context_chunks if c.get("document_id")}
    verified = [c for c in citations if c in retrieved]
    dropped = [c for c in citations if c not in retrieved]
    return verified, dropped


def synthesize_node(state: AgentState) -> dict:
    """Synthesize the final answer from all agent outputs and context."""
    chunks = state.get("context_chunks", [])

    context = None
    if chunks:
        context = "\n\n".join(c["text"] for c in chunks if c.get("text"))

    answer, degraded, telemetry = _call_llm(state["messages"], context)

    # Citation integrity: verify the model's cited document IDs against the
    # chunks actually retrieved for this query before anything is sent back.
    cited = _extract_citations(answer)
    if cited:
        verified, dropped = validate_citations(cited, chunks)
        citations = verified
        citations_unverified = bool(dropped)
        if dropped:
            logger.warning(
                "ai.citation_unverified",
                extra={
                    "cited": cited,
                    "dropped": dropped,
                    "retrieved_ids": sorted(
                        {c.get("document_id") for c in chunks if c.get("document_id")}
                    ),
                    "workspace_id": state.get("workspace_id"),
                    "organization_id": state.get("organization_id"),
                },
            )
    else:
        # No explicit citation claims: fall back to the ids of chunks that were
        # actually retrieved. These are verified by construction, so no flag.
        citations = list(
            dict.fromkeys(c.get("document_id") for c in chunks if c.get("document_id"))
        )
        citations_unverified = False
    answer = _strip_citation_line(answer)

    action: AgentAction = {
        "tool_name": "coordinator.synthesize",
        "tool_input": {"chunks_used": len(chunks), "citations": citations},
        "tool_output": f"Synthesized answer using {len(chunks)} context chunks",
        "timestamp": _now(),
    }

    return {
        "final_answer": answer,
        "degraded": degraded,
        "citations": citations,
        "citations_unverified": citations_unverified,
        "llm_telemetry": telemetry,
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
