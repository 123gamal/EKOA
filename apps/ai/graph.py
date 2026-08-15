"""LangGraph multi-agent orchestration for EKOA."""

from __future__ import annotations

import asyncio
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
    retrieval_latency_ms: int | None
    # Phase 15
    intent: str | None
    conversation_summary: str | None
    # Phase 16
    qa_flags: list[str]
    user_id: str | None


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


def security_node(state: AgentState) -> dict:
    """Apply input guardrails to the incoming message. Entry point of the graph.

    Guardrails are flag-and-continue for this phase: a flagged message is
    logged (structured) and carried in state so downstream visibility (audit
    log) can record it, but it is not blocked outright. Blocking on heuristics
    would produce false positives on legitimate long/technical messages.

    Was embedded in ``coordinator_node`` prior to Phase 15; pulled out into
    its own node so guardrail checks are independently visible in the action
    trace and have room for real policy logic later, separate from routing.
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
        "tool_name": "security.guardrail_check",
        "tool_input": {"query_preview": user_msg[:120]},
        "tool_output": (
            f"{len(flags)} guardrail flag(s) raised" if flags else "No guardrail flags raised"
        ),
        "timestamp": _now(),
    }

    return {
        "guardrail_flags": flags,
        "actions": state["actions"] + [action],
    }


def coordinator_node(state: AgentState) -> dict:
    """Acknowledge the query and hand off to the planner for real routing.

    Prior to Phase 15 this node's "routing" was a hardcoded stub string with
    no actual logic — see ``planner_node`` for the real intent classification
    that now drives routing. This node stays as a lightweight orchestration
    marker (and to keep the "coordinator.analyze" action name existing
    callers/tests already look for).
    """
    user_msg = state["messages"][-1]["content"] if state["messages"] else ""

    action: AgentAction = {
        "tool_name": "coordinator.analyze",
        "tool_input": {"query": user_msg},
        "tool_output": "Query received, handing off to planner for routing",
        "timestamp": _now(),
    }

    return {
        "actions": state["actions"] + [action],
    }


_INTENT_VALUES = ("qa", "workflow", "chitchat", "analytics", "research", "notifications")


def _classify_intent(user_msg: str) -> str:
    """Classify the user's message into a routing intent via a small, cheap
    LLM call. Defaults to "qa" (the pre-Phase-15 behavior: always retrieve
    and synthesize) on any failure or ambiguous output — a wrong "qa"
    classification just does unnecessary retrieval, while a wrong "chitchat"
    classification could skip retrieval a real question needed, so "qa" is
    the safe default in both directions.
    """
    if not user_msg.strip():
        return "qa"

    prompt = (
        "Classify the user's message into exactly one category. Reply with "
        "ONLY one word, no punctuation:\n"
        "- chitchat: greetings or social small talk with no informational "
        "need (e.g. \"hi\", \"thanks\", \"how are you\")\n"
        "- workflow: the user is asking about the status of, or wants to "
        "run, an automation/workflow\n"
        "- analytics: the user is asking about usage stats, AI cost/token "
        "spend, document counts, or other operational metrics for their "
        "workspace (e.g. \"how many documents were uploaded this week\", "
        "\"what's our AI cost this month\")\n"
        "- research: the user's question is complex/multi-part and likely "
        "needs more than one search pass over the knowledge base to answer "
        "fully (e.g. comparing multiple documents, or a question with "
        "several distinct sub-questions)\n"
        "- notifications: the user is asking whether they have any "
        "notifications/alerts, or wants their notifications listed\n"
        "- qa: anything else, including any single, straightforward factual "
        "question, request for information, or document-related query\n\n"
        f"Message: {user_msg[:500]}\n\nCategory:"
    )

    deepseek_key = settings.DEEPSEEK_API_KEY or settings.LLM_API_KEY
    if deepseek_key and not deepseek_key.startswith("sk-your"):
        try:
            from openai import OpenAI
            client = OpenAI(api_key=deepseek_key, base_url=settings.DEEPSEEK_BASE_URL)
            resp = client.chat.completions.create(
                model=settings.DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=10,
            )
            raw = (resp.choices[0].message.content or "").strip().lower()
            for value in _INTENT_VALUES:
                if value in raw:
                    return value
        except Exception as exc:
            llm_logger.warning(
                "planner_classify_failed",
                extra={"provider": "deepseek", "error": f"{type(exc).__name__}: {exc}"},
            )

    gemini_key = settings.GEMINI_API_KEY
    if gemini_key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_key)
            model = genai.GenerativeModel(settings.GEMINI_MODEL)
            resp = model.generate_content(prompt)
            raw = (resp.text or "").strip().lower()
            for value in _INTENT_VALUES:
                if value in raw:
                    return value
        except Exception as exc:
            llm_logger.warning(
                "planner_classify_failed",
                extra={"provider": "gemini", "error": f"{type(exc).__name__}: {exc}"},
            )

    return "qa"


async def planner_node(state: AgentState) -> dict:
    """Real intent classification driving routing — replaces the previous
    hardcoded linear sequencer. Offloaded to a thread for the same reason as
    retriever_node/synthesize_node (see their docstrings): it makes a real
    blocking LLM HTTP call.
    """
    user_msg = state["messages"][-1]["content"] if state["messages"] else ""
    intent = await asyncio.to_thread(_classify_intent, user_msg)

    action: AgentAction = {
        "tool_name": "planner.route",
        "tool_input": {"query_preview": user_msg[:120]},
        "tool_output": f"Classified intent as '{intent}'",
        "timestamp": _now(),
    }

    return {
        "intent": intent,
        "actions": state["actions"] + [action],
    }


# Conversation turns kept verbatim when compacting; older turns get folded
# into conversation_summary instead of being sent raw to the LLM.
MEMORY_COMPACTION_THRESHOLD = 12
MEMORY_KEEP_RECENT = 6


def memory_node(state: AgentState) -> dict:
    """Compact older conversation turns into a running summary once a chat
    gets long, so ``synthesize_node`` doesn't send the entire raw history to
    the LLM on every turn.

    Deliberately scoped to per-request compaction only — nothing is
    persisted across requests/sessions here; that would be a materially
    bigger feature (a real memory store) left for future work. A no-op
    (returns no new summary) below the threshold, so short conversations are
    completely unaffected.
    """
    messages = state.get("messages", [])
    if len(messages) <= MEMORY_COMPACTION_THRESHOLD:
        return {"actions": state["actions"]}

    older = messages[:-MEMORY_KEEP_RECENT]
    summary_source = "\n".join(f"{m['role']}: {m['content']}" for m in older if m.get("content"))
    # A plain truncation, not an LLM call: keeps this node cheap and
    # dependency-free. "Summary" here means "bounded-size compaction", not
    # necessarily a fluent LLM-written abstract — good enough to keep
    # synthesize_node's prompt bounded without an extra round-trip per turn.
    summary = summary_source[-2000:]

    action: AgentAction = {
        "tool_name": "memory.compact",
        "tool_input": {"messages_compacted": len(older)},
        "tool_output": f"Compacted {len(older)} older message(s) into a running summary",
        "timestamp": _now(),
    }

    return {
        "conversation_summary": summary,
        "actions": state["actions"] + [action],
    }


async def _workflow_status_summary(workspace_id: str) -> str:
    """Async DB read of a workspace's Workflow/WorkflowRun rows, composed
    into a conversational status summary.

    Uses the AI service's own async DB engine (``apps.api.db.engine``, the
    same one every other route in this service already depends on) rather
    than a sync engine — no thread offload needed here, an async query is
    already non-blocking. Two prior attempts at a sync path both failed live
    with import errors from picking up worker-only dependencies transitively
    (``apps.worker.workflow_executor`` needs ``fitz``/PyMuPDF; a bare
    ``create_engine(...)`` needs ``psycopg2``, neither installed in this
    service's image) — this sidesteps that class of bug entirely by not
    introducing a second DB access path.
    """
    import uuid as _uuid
    from sqlalchemy import select
    from apps.api.db.engine import get_session_factory
    from apps.api.models.workflow import Workflow, WorkflowRun

    try:
        ws_uuid = _uuid.UUID(workspace_id) if workspace_id else None
    except ValueError:
        ws_uuid = None
    if ws_uuid is None:
        return "I don't have a workspace to check workflows in."

    async with get_session_factory()() as db:
        stmt = (
            select(Workflow)
            .where(Workflow.workspace_id == ws_uuid, Workflow.deleted_at.is_(None))
            .order_by(Workflow.created_at.desc())
            .limit(5)
        )
        workflows = (await db.execute(stmt)).scalars().all()
        if not workflows:
            return (
                "No workflows have been run in this workspace yet. You can start one "
                "from the Workflows page using one of the available templates."
            )

        lines = []
        for wf in workflows:
            run_stmt = (
                select(WorkflowRun)
                .where(WorkflowRun.workflow_id == wf.id)
                .order_by(WorkflowRun.created_at.desc())
                .limit(1)
            )
            latest_run = (await db.execute(run_stmt)).scalars().first()
            if latest_run is None:
                lines.append(f"- **{wf.name}**: created, not yet run (status: {wf.status})")
            elif latest_run.approval_status == "PENDING":
                lines.append(f"- **{wf.name}**: run is awaiting approval")
            else:
                lines.append(f"- **{wf.name}**: last run status is {latest_run.status}")
        return "Here's the workflow status for this workspace:\n\n" + "\n".join(lines)


async def workflow_node(state: AgentState) -> dict:
    """Read-only status bridge to the existing workflow engine
    (``apps/worker/workflow_executor.py``) — reports on runs/templates in
    conversational form. Deliberately does NOT trigger new workflow runs:
    that needs write-permission checks and the full start UX, out of scope
    for this slice (same kind of intentionally-partial, disclosed boundary
    as Phase 13's workspace-role enforcement).
    """
    workspace_id = state.get("workspace_id", "")
    try:
        summary = await _workflow_status_summary(workspace_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("workflow_node_failed", extra={"error": f"{type(exc).__name__}: {exc}"})
        summary = "I couldn't look up workflow status right now."

    action: AgentAction = {
        "tool_name": "workflow.status",
        "tool_input": {"workspace_id": workspace_id},
        "tool_output": "Reported workflow status (read-only)",
        "timestamp": _now(),
    }

    return {
        "final_answer": summary,
        "actions": state["actions"] + [action],
    }


async def _analytics_summary(workspace_id: str) -> str:
    """Async DB read of a workspace's AI usage + document stats over the
    last 7 days, composed into a conversational summary.

    Same async-engine pattern as ``_workflow_status_summary`` (deliberately
    NOT a second/sync DB access path — see that function's docstring for the
    two failure modes that pattern avoids).
    """
    import uuid as _uuid
    from datetime import timedelta
    from sqlalchemy import select
    from apps.api.db.engine import get_session_factory
    from apps.api.models.ai_call_log import AiCallLog
    from apps.api.models.document import Document

    try:
        ws_uuid = _uuid.UUID(workspace_id) if workspace_id else None
    except ValueError:
        ws_uuid = None
    if ws_uuid is None:
        return "I don't have a workspace to check usage for."

    since = datetime.now(timezone.utc) - timedelta(days=7)
    async with get_session_factory()() as db:
        doc_stmt = select(Document).where(
            Document.workspace_id == ws_uuid, Document.deleted_at.is_(None)
        )
        docs = list((await db.execute(doc_stmt)).scalars().all())

        call_stmt = select(AiCallLog).where(
            AiCallLog.workspace_id == ws_uuid, AiCallLog.created_at >= since
        )
        calls = list((await db.execute(call_stmt)).scalars().all())

    by_status: dict[str, int] = {}
    for d in docs:
        by_status[d.status] = by_status.get(d.status, 0) + 1
    status_line = ", ".join(f"{count} {name}" for name, count in by_status.items()) or "none"

    latencies = [c.latency_ms for c in calls if c.latency_ms is not None]
    avg_latency = round(sum(latencies) / len(latencies)) if latencies else None
    total_tokens = sum(c.total_tokens or 0 for c in calls)
    est_cost = sum(float(c.cost_estimate) for c in calls if c.cost_estimate is not None)

    lines = [
        f"- **Documents**: {len(docs)} total ({status_line})",
        f"- **AI calls (last 7 days)**: {len(calls)}",
    ]
    if avg_latency is not None:
        lines.append(f"- **Average latency**: {avg_latency}ms")
    lines.append(f"- **Total tokens (last 7 days)**: {total_tokens}")
    lines.append(f"- **Estimated cost (last 7 days)**: ${est_cost:.4f} (estimate, not a billed figure)")

    return "Here's the usage summary for this workspace:\n\n" + "\n".join(lines)


async def analytics_node(state: AgentState) -> dict:
    """Read-only usage/cost summary bridge — answers "how many documents",
    "what's our AI cost" style questions conversationally. Reuses the same
    tenant-scoped data ``apps/api/routes/analytics.py`` already exposes over
    HTTP, queried directly here so chat doesn't need a self-HTTP round-trip.
    """
    workspace_id = state.get("workspace_id", "")
    try:
        summary = await _analytics_summary(workspace_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("analytics_node_failed", extra={"error": f"{type(exc).__name__}: {exc}"})
        summary = "I couldn't look up usage analytics right now."

    action: AgentAction = {
        "tool_name": "analytics.summary",
        "tool_input": {"workspace_id": workspace_id},
        "tool_output": "Reported usage analytics (read-only)",
        "timestamp": _now(),
    }

    return {
        "final_answer": summary,
        "actions": state["actions"] + [action],
    }


async def _notifications_summary(user_id: str) -> str:
    """Async DB read of a user's most recent notifications, composed into a
    conversational summary. Same async-engine pattern as
    ``_workflow_status_summary``/``_analytics_summary``."""
    import uuid as _uuid
    from sqlalchemy import select
    from apps.api.db.engine import get_session_factory
    from apps.api.models.notification import Notification

    try:
        user_uuid = _uuid.UUID(user_id) if user_id else None
    except ValueError:
        user_uuid = None
    if user_uuid is None:
        return "I don't know which user to check notifications for."

    async with get_session_factory()() as db:
        stmt = (
            select(Notification)
            .where(Notification.user_id == user_uuid)
            .order_by(Notification.created_at.desc())
            .limit(10)
        )
        notifications = (await db.execute(stmt)).scalars().all()

    unread = [n for n in notifications if n.read_at is None]
    if not notifications:
        return "You have no notifications."

    lines = [f"You have {len(unread)} unread notification(s):" if unread else "You have no unread notifications. Recent notifications:"]
    for n in (unread or notifications)[:10]:
        lines.append(f"- **{n.title}**: {n.body or ''}".rstrip())
    return "\n".join(lines)


async def notification_node(state: AgentState) -> dict:
    """Read-only bridge answering "do I have any notifications?" style
    questions — same shape as ``workflow_node``/``analytics_node``."""
    user_id = state.get("user_id") or ""
    try:
        summary = await _notifications_summary(user_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("notification_node_failed", extra={"error": f"{type(exc).__name__}: {exc}"})
        summary = "I couldn't look up notifications right now."

    action: AgentAction = {
        "tool_name": "notifications.summary",
        "tool_input": {"user_id": user_id},
        "tool_output": "Reported notifications (read-only)",
        "timestamp": _now(),
    }

    return {
        "final_answer": summary,
        "actions": state["actions"] + [action],
    }


# Hard cap on retrieval passes: an LLM deciding "one more search would help"
# on every pass could loop indefinitely without a bound. This is exactly the
# unbounded-agent-loop risk Phase 12's latency work flagged — capped
# explicitly rather than left to the model's judgment.
MAX_RESEARCH_PASSES = 3


def _should_refine_query(user_msg: str, chunks: list[dict]) -> str | None:
    """Ask a cheap LLM call whether a narrower follow-up query would help,
    given what the first retrieval pass found. Returns the follow-up query
    string, or None to stop refining (including on any failure — a failed
    refinement check should not block the answer)."""
    if not chunks:
        return None
    preview = "\n".join(f"- {c.get('text', '')[:200]}" for c in chunks[:5])
    prompt = (
        "A user asked a multi-part or complex question. Here is a preview of "
        "what the first knowledge-base search pass found:\n\n"
        f"{preview}\n\n"
        f"Original question: {user_msg[:500]}\n\n"
        "Would a second, more targeted search query uncover additional "
        "relevant information not already covered above? If yes, reply with "
        "ONLY the follow-up search query text (no explanation). If no, reply "
        "with exactly: NONE"
    )
    deepseek_key = settings.DEEPSEEK_API_KEY or settings.LLM_API_KEY
    if not (deepseek_key and not deepseek_key.startswith("sk-your")):
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=deepseek_key, base_url=settings.DEEPSEEK_BASE_URL)
        resp = client.chat.completions.create(
            model=settings.DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=60,
        )
        raw = (resp.choices[0].message.content or "").strip()
        if not raw or raw.upper().startswith("NONE"):
            return None
        return raw
    except Exception as exc:
        llm_logger.warning(
            "research_refine_failed", extra={"error": f"{type(exc).__name__}: {exc}"}
        )
        return None


async def research_node(state: AgentState) -> dict:
    """Iterative retrieval for complex/multi-part questions: up to
    ``MAX_RESEARCH_PASSES`` retrieval passes, each pass's chunks merged
    (deduped by document_id + chunk_index) before handing off to
    ``document_node``/``synthesize_node`` — the same downstream path the
    "qa" intent uses, just with richer context_chunks.
    """
    user_msg = state["messages"][-1]["content"] if state["messages"] else ""
    collection_name = state.get("collection_name", "ekoa_default")
    organization_id = state.get("organization_id")
    workspace_id = state.get("workspace_id")

    seen: set[tuple] = set()
    merged: list[dict] = []
    queries = [user_msg]
    passes_run = 0

    def _add(chunks: list[dict]) -> None:
        for c in chunks:
            key = (c.get("document_id"), c.get("chunk_index"))
            if key not in seen:
                seen.add(key)
                merged.append(c)

    start = time.perf_counter()
    query = queries[0]
    for _ in range(MAX_RESEARCH_PASSES):
        try:
            chunks = await asyncio.to_thread(
                retrieve_chunks,
                query=query,
                collection_name=collection_name,
                organization_id=organization_id,
                workspace_id=workspace_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("research_node_retrieval_failed", extra={"error": f"{type(exc).__name__}: {exc}"})
            chunks = []
        _add(chunks)
        passes_run += 1
        if passes_run >= MAX_RESEARCH_PASSES:
            break
        follow_up = await asyncio.to_thread(_should_refine_query, user_msg, chunks)
        if not follow_up:
            break
        query = follow_up
    retrieval_latency_ms = round((time.perf_counter() - start) * 1000)

    action: AgentAction = {
        "tool_name": "research.iterative_retrieve",
        "tool_input": {"query": user_msg, "passes": passes_run},
        "tool_output": f"Ran {passes_run} retrieval pass(es), merged {len(merged)} unique chunks",
        "timestamp": _now(),
    }

    return {
        "context_chunks": merged,
        "retrieval_latency_ms": retrieval_latency_ms,
        "actions": state["actions"] + [action],
    }


async def retriever_node(state: AgentState) -> dict:
    """Query Qdrant vector store for relevant chunks.

    ``retrieve_chunks`` is synchronous and does real CPU-bound work
    (SentenceTransformer embedding) plus a blocking Qdrant network call.
    Run it in a thread so it doesn't block the event loop that every other
    concurrent request's coroutine also depends on — see Phase 12's
    latency investigation (docs/performance-and-nfrs.md) for why this
    mattered: without the offload, one slow request head-of-line-blocks
    every other request on the same AI service process.
    """
    user_msg = state["messages"][-1]["content"] if state["messages"] else ""

    action_input = {"query": user_msg, "collection": state.get("collection_name", "ekoa_default")}
    start = time.perf_counter()
    try:
        chunks = await asyncio.to_thread(
            retrieve_chunks,
            query=user_msg,
            collection_name=state.get("collection_name", "ekoa_default"),
            organization_id=state.get("organization_id"),
            workspace_id=state.get("workspace_id"),
        )
        action_output = f"Retrieved {len(chunks)} relevant chunks from vector store"
    except Exception as e:
        chunks = []
        action_output = f"Retrieval failed: {e}"
    retrieval_latency_ms = round((time.perf_counter() - start) * 1000)

    action: AgentAction = {
        "tool_name": "retriever.search",
        "tool_input": action_input,
        "tool_output": action_output,
        "timestamp": _now(),
    }

    return {
        "context_chunks": chunks,
        "retrieval_latency_ms": retrieval_latency_ms,
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


def _qa_self_check(answer: str, context: str | None) -> list[str]:
    """Cheap second LLM call: given the answer + retrieved context, flag any
    claim in the answer not supported by the context. Flag-and-continue, same
    philosophy as ``check_input_guardrails`` — this never blocks the answer,
    it only surfaces flags for the caller to display (same treatment as
    ``citations_unverified``). Returns [] on no context (nothing to check
    against), no flags found, or any failure (a broken self-check must not
    break the primary answer).
    """
    if not context or not answer:
        return []
    prompt = (
        "You are a fact-checking pass. Given the CONTEXT and the ANSWER below, "
        "list any specific factual claim in the ANSWER that is NOT supported "
        "by the CONTEXT. Reply with each unsupported claim on its own line, "
        "prefixed with '- '. If every claim in the ANSWER is supported by the "
        "CONTEXT, reply with exactly: NONE\n\n"
        f"CONTEXT:\n{context[:6000]}\n\nANSWER:\n{answer[:2000]}"
    )
    deepseek_key = settings.DEEPSEEK_API_KEY or settings.LLM_API_KEY
    if not (deepseek_key and not deepseek_key.startswith("sk-your")):
        return []
    try:
        from openai import OpenAI
        client = OpenAI(api_key=deepseek_key, base_url=settings.DEEPSEEK_BASE_URL)
        resp = client.chat.completions.create(
            model=settings.DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=300,
        )
        raw = (resp.choices[0].message.content or "").strip()
        if not raw or raw.upper().startswith("NONE"):
            return []
        return [line.lstrip("- ").strip() for line in raw.splitlines() if line.strip()]
    except Exception as exc:
        llm_logger.warning("qa_self_check_failed", extra={"error": f"{type(exc).__name__}: {exc}"})
        return []


def _messages_for_llm(state: AgentState) -> list[dict[str, str]]:
    """Apply memory compaction (if ``memory_node`` produced a summary) before
    handing messages to the LLM: older turns collapse into one summary line,
    only the most recent ``MEMORY_KEEP_RECENT`` stay verbatim. No-op (returns
    the raw messages untouched) when no summary was produced."""
    messages = state["messages"]
    summary = state.get("conversation_summary")
    if not summary:
        return messages
    recent = messages[-MEMORY_KEEP_RECENT:]
    return [
        {"role": "user", "content": f"[Summary of earlier conversation: {summary}]"},
        *recent,
    ]


async def synthesize_node(state: AgentState) -> dict:
    """Synthesize the final answer from all agent outputs and context.

    ``_call_llm`` uses synchronous provider SDKs (OpenAI/google.generativeai)
    and makes a real blocking HTTP round-trip — offloaded to a thread for the
    same reason as ``retriever_node`` (see its docstring).
    """
    chunks = state.get("context_chunks", [])

    context = None
    if chunks:
        context = "\n\n".join(c["text"] for c in chunks if c.get("text"))

    answer, degraded, telemetry = await asyncio.to_thread(
        _call_llm, _messages_for_llm(state), context
    )

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

    # Output-side guardrail check (Phase 15, part of the security node's
    # remit even though it runs here at generation time): the same cheap
    # heuristics applied to the user's input, now applied to what the model
    # is about to send back. Flagged, not blocked — consistent with
    # check_input_guardrails' documented flag-and-continue philosophy.
    output_flags = check_input_guardrails(answer)
    if output_flags:
        for flag in output_flags:
            logger.warning(
                "ai.output_guardrail_triggered",
                extra={
                    "reason": flag["type"],
                    "detail": flag.get("detail"),
                    "workspace_id": state.get("workspace_id"),
                    "organization_id": state.get("organization_id"),
                },
            )
    guardrail_flags = state.get("guardrail_flags", []) + output_flags

    action: AgentAction = {
        "tool_name": "coordinator.synthesize",
        "tool_input": {"chunks_used": len(chunks), "citations": citations},
        "tool_output": f"Synthesized answer using {len(chunks)} context chunks",
        "timestamp": _now(),
    }

    # QA self-check (Phase 16 Part B-4): a second, cheap LLM call flags any
    # claim in the answer not supported by the retrieved context. Skipped
    # entirely when the answer came from the degraded fallback (no real LLM
    # answered, so there's nothing meaningful to fact-check).
    qa_flags: list[str] = []
    if not degraded:
        qa_flags = await asyncio.to_thread(_qa_self_check, answer, context)
    qa_action: AgentAction = {
        "tool_name": "qa.self_check",
        "tool_input": {"chunks_available": len(chunks)},
        "tool_output": (
            f"{len(qa_flags)} unsupported claim(s) flagged" if qa_flags else "No unsupported claims flagged"
        ),
        "timestamp": _now(),
    }

    return {
        "final_answer": answer,
        "degraded": degraded,
        "citations": citations,
        "citations_unverified": citations_unverified,
        "llm_telemetry": telemetry,
        "guardrail_flags": guardrail_flags,
        "qa_flags": qa_flags,
        "actions": state["actions"] + [action, qa_action],
    }


def intent_router_condition(
    state: AgentState,
) -> Literal["memory", "workflow", "analytics", "research", "notifications", "synthesize"]:
    """Route based on the planner's real intent classification (Phase 15,
    extended Phase 16 with analytics/research/notifications).

    "qa" (the default) takes the full retrieve-and-synthesize path via
    ``memory`` first; "chitchat" skips straight to synthesis (no retrieval
    needed for a greeting); "workflow" goes to the read-only workflow
    bridge; "analytics" goes to the read-only usage-summary bridge;
    "research" goes to the iterative multi-pass retriever instead of the
    single-pass one; "notifications" goes to the read-only notifications
    bridge.
    """
    intent = state.get("intent") or "qa"
    if intent == "chitchat":
        return "synthesize"
    if intent == "workflow":
        return "workflow"
    if intent == "analytics":
        return "analytics"
    if intent == "research":
        return "research"
    if intent == "notifications":
        return "notifications"
    return "memory"


# ── Build Graph ──────────────────────────────────────────────────────────────


def build_agent_graph() -> StateGraph:
    """Construct the LangGraph agent orchestration graph."""
    workflow = StateGraph(AgentState)

    workflow.add_node("security", security_node)
    workflow.add_node("coordinator", coordinator_node)
    workflow.add_node("planner", planner_node)
    workflow.add_node("memory", memory_node)
    workflow.add_node("retriever", retriever_node)
    workflow.add_node("document", document_node)
    workflow.add_node("workflow", workflow_node)
    workflow.add_node("analytics", analytics_node)
    workflow.add_node("research", research_node)
    workflow.add_node("notifications", notification_node)
    workflow.add_node("synthesize", synthesize_node)

    workflow.set_entry_point("security")
    workflow.add_edge("security", "coordinator")
    workflow.add_edge("coordinator", "planner")

    workflow.add_conditional_edges(
        "planner",
        intent_router_condition,
        {
            "memory": "memory",
            "workflow": "workflow",
            "analytics": "analytics",
            "research": "research",
            "notifications": "notifications",
            "synthesize": "synthesize",
        },
    )
    workflow.add_edge("memory", "retriever")
    workflow.add_edge("retriever", "document")
    workflow.add_edge("research", "document")
    workflow.add_edge("document", "synthesize")
    workflow.add_edge("workflow", END)
    workflow.add_edge("analytics", END)
    workflow.add_edge("notifications", END)
    workflow.add_edge("synthesize", END)

    return workflow.compile()


# Compiled graph instance (lazily initialized)
_graph_instance: StateGraph | None = None


def get_agent_graph() -> StateGraph:
    global _graph_instance
    if _graph_instance is None:
        _graph_instance = build_agent_graph()
    return _graph_instance
