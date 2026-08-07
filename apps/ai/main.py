"""EKOA AI Service – LangGraph multi-agent orchestration with SSE streaming."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select, text

from apps.ai.graph import get_agent_graph, AgentState
from apps.ai.deps import get_current_user, assert_workspace_access_for_user
from apps.api.models.user import User
from apps.api.models.workspace import Workspace
from apps.api.models.conversation import Conversation, Message
from apps.api.db.engine import get_db, get_engine
from ekoa_config.settings import get_settings, resolve_cors_origins
from ekoa_config.logging import setup_logging, CorrelationIdMiddleware
from ekoa_config.rate_limit import RateLimitMiddleware
from ekoa_types.conversation import ConversationResponse, MessageResponse
from ekoa_types.pagination import (
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    Paginated,
)
from ekoa_utils.naming import workspace_collection_name

setup_logging("ai")

settings = get_settings()

app = FastAPI(title="EKOA AI Service", version="0.1.0")
router = APIRouter(prefix="/api/v1/ai")

cors_origins = resolve_cors_origins(settings)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(CorrelationIdMiddleware)

# General default per-IP rate limit for every request (except /health).
app.add_middleware(RateLimitMiddleware)


# ── Request / Response Schemas ───────────────────────────────────────────────


class ChatRequest(BaseModel):
    workspace_id: str
    conversation_id: str | None = None
    message: str = Field(..., min_length=1)
    history: list[dict[str, str]] = Field(default_factory=list)


class ChatResponse(BaseModel):
    conversation_id: str
    reply: str
    sources: list[str] = Field(default_factory=list)
    actions: list[dict] = Field(default_factory=list)
    degraded: bool = False
    created_at: str


# ── Helper ────────────────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _resolve_org_id(db: AsyncSession, workspace_id: str) -> uuid.UUID | None:
    """Resolve the organization that owns a workspace (None if it doesn't exist)."""
    try:
        ws_uuid = uuid.UUID(workspace_id)
    except ValueError:
        return None
    stmt = select(Workspace.organization_id).where(Workspace.id == ws_uuid)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _load_history(db: AsyncSession, conversation_id: uuid.UUID) -> list[dict[str, str]]:
    """Load persisted messages for a conversation in chronological order.

    The database is the authoritative source of conversation history. The
    client-supplied ``history`` array is used only as a fallback when a
    conversation has no persisted messages yet (e.g. requests created by a
    client that managed its own history before persistence shipped).
    """
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    result = await db.execute(stmt)
    return [{"role": m.role, "content": m.content} for m in result.scalars().all()]


async def _append_message(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    role: str,
    content: str,
) -> Message:
    message = Message(conversation_id=conversation_id, role=role, content=content)
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return message


async def _get_or_create_conversation(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    conversation_id: str | None,
    message: str,
) -> Conversation:
    """Create a conversation on first message, or load the caller's existing one.

    The conversation is created on the first message if the client does not
    supply a ``conversation_id``; afterwards the client echoes the returned
    id. A supplied id that is not the caller's conversation in the requested
    workspace is rejected with 404 (no cross-user/tenant disclosure).
    """
    if conversation_id is None:
        org_id = await _resolve_org_id(db, workspace_id)
        if org_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workspace not found",
            )
        title = (message[:60] + "…") if len(message) > 60 else message
        conversation = Conversation(
            title=title,
            workspace_id=uuid.UUID(workspace_id),
            organization_id=org_id,
            user_id=user.id,
        )
        db.add(conversation)
        await db.commit()
        await db.refresh(conversation)
        return conversation

    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid conversation_id",
        )

    stmt = select(Conversation).where(Conversation.id == conv_uuid)
    conversation = (await db.execute(stmt)).scalar_one_or_none()
    if (
        conversation is None
        or conversation.user_id != user.id
        or str(conversation.workspace_id) != workspace_id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    return conversation


def _build_initial_state(
    req: ChatRequest,
    organization_id: uuid.UUID | None,
    messages: list[dict[str, str]],
) -> AgentState:
    return {
        "messages": messages,
        "actions": [],
        "context_chunks": [],
        "workspace_id": req.workspace_id,
        "organization_id": str(organization_id) if organization_id else None,
        "collection_name": workspace_collection_name(req.workspace_id) if req.workspace_id else "ekoa_default",
        "final_answer": None,
    }


# ── REST Endpoints ───────────────────────────────────────────────────────────


@app.get("/health")
async def health_check():
    """Liveness probe that verifies real dependencies, not just the process.

    Checks the database and Qdrant reachability. Returns 200 only when both
    are healthy; otherwise 503 so Docker healthchecks fail when the service is
    actually degraded.
    """
    dependencies: dict[str, str] = {}
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        dependencies["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        dependencies["database"] = f"error: {type(exc).__name__}"

    try:
        from apps.ai.retriever import _get_qdrant
        _get_qdrant().get_collections()
        dependencies["qdrant"] = "ok"
    except Exception as exc:  # noqa: BLE001
        dependencies["qdrant"] = f"error: {type(exc).__name__}"

    healthy = all(v == "ok" for v in dependencies.values())
    body = {
        "status": "healthy" if healthy else "unhealthy",
        "service": "ekoa-ai",
        "version": "0.1.0",
        "dependencies": dependencies,
    }
    if not healthy:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=body)
    return body


@router.post("/chat", response_model=ChatResponse)
async def chat_sync(
    req: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Synchronous chat endpoint – returns the final answer.

    Persists the conversation and both the user and assistant messages so a
    subsequent request can reload full history from the database.
    """
    await assert_workspace_access_for_user(current_user, req.workspace_id, db)
    conversation = await _get_or_create_conversation(
        db, current_user, req.workspace_id, req.conversation_id, req.message
    )
    history = await _load_history(db, conversation.id)
    messages = history or req.history
    messages = messages + [{"role": "user", "content": req.message}]

    organization_id = await _resolve_org_id(db, req.workspace_id)
    graph = get_agent_graph()
    state = _build_initial_state(req, organization_id, messages)

    await _append_message(db, conversation.id, "user", req.message)
    try:
        result = await graph.ainvoke(state)
    except Exception:
        db.rollback()
        raise
    reply = result.get("final_answer") or "No answer generated."
    await _append_message(db, conversation.id, "assistant", reply)

    return ChatResponse(
        conversation_id=str(conversation.id),
        reply=reply,
        sources=list(set(c["document_id"] for c in result.get("context_chunks", []) if c.get("document_id"))),
        actions=[dict(a) for a in result.get("actions", [])],
        degraded=bool(result.get("degraded")),
        created_at=_now(),
    )


@router.post("/chat/stream")
async def chat_stream(
    req: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Streaming SSE endpoint – pushes agent actions and final answer as events.

    Persists the user message immediately and the assistant message once the
    final answer has been produced, so history is durable even across streams.
    """
    await assert_workspace_access_for_user(current_user, req.workspace_id, db)
    conversation = await _get_or_create_conversation(
        db, current_user, req.workspace_id, req.conversation_id, req.message
    )
    history = await _load_history(db, conversation.id)
    messages = history or req.history
    messages = messages + [{"role": "user", "content": req.message}]

    organization_id = await _resolve_org_id(db, req.workspace_id)
    graph = get_agent_graph()
    state = _build_initial_state(req, organization_id, messages)
    conversation_id = str(conversation.id)

    await _append_message(db, conversation.id, "user", req.message)

    async def event_generator():
        final_answer: str | None = None
        try:
            async for event in graph.astream_events(state, version="v2"):
                kind = event.get("event")

                if kind == "on_chain_start":
                    node_name = event.get("name", "")
                    if node_name in ("coordinator", "retriever", "document", "synthesize"):
                        yield {
                            "event": "agent_start",
                            "data": json.dumps({"agent": node_name, "timestamp": _now()}),
                        }

                elif kind == "on_chain_end":
                    node_name = event.get("name", "")
                    output = event.get("data", {}).get("output", {})
                    if isinstance(output, dict):
                        actions = output.get("actions", [])

                        if actions:
                            last_action = actions[-1]
                            yield {
                                "event": "agent_action",
                                "data": json.dumps({
                                    "agent": node_name,
                                    "action": last_action.get("tool_name"),
                                    "output": last_action.get("tool_output"),
                                    "timestamp": _now(),
                                }),
                            }

                        if node_name == "synthesize":
                            final = output.get("final_answer", "")
                            final_answer = final
                            yield {
                                "event": "agent_complete",
                                "data": json.dumps({"agent": node_name, "timestamp": _now()}),
                            }

                            chunks = output.get("context_chunks", [])
                            sources = list(set(c["document_id"] for c in chunks if isinstance(c, dict) and c.get("document_id")))

                            yield {
                                "event": "message",
                                "data": json.dumps({
                                    "conversation_id": conversation_id,
                                    "reply": final,
                                    "sources": sources,
                                    "actions": [dict(a) for a in output.get("actions", [])],
                                    "degraded": bool(output.get("degraded")),
                                    "created_at": _now(),
                                }),
                            }
        finally:
            if final_answer:
                await _append_message(db, conversation.id, "assistant", final_answer)

        yield {"event": "done", "data": ""}

    return EventSourceResponse(event_generator())


@router.get("/conversations", response_model=Paginated[ConversationResponse])
async def list_conversations(
    workspace_id: str = Query(..., description="Filter conversations by workspace ID"),
    page: int = Query(DEFAULT_PAGE, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Items per page"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the current user's conversations in a workspace (paginated, latest first)."""
    await assert_workspace_access_for_user(current_user, workspace_id, db)
    try:
        ws_uuid = uuid.UUID(workspace_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid workspace_id",
        )

    base = select(Conversation).where(
        Conversation.workspace_id == ws_uuid,
        Conversation.user_id == current_user.id,
    )
    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()

    stmt = (
        base.order_by(Conversation.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list((await db.execute(stmt)).scalars().all())
    return Paginated.create(items, total, page, page_size)


@router.get("/conversations/{conversation_id}/messages", response_model=Paginated[MessageResponse])
async def list_messages(
    conversation_id: str,
    page: int = Query(DEFAULT_PAGE, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Items per page"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List persisted messages for one of the caller's conversations (paginated, oldest first)."""
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid conversation_id",
        )

    stmt = select(Conversation).where(Conversation.id == conv_uuid)
    conversation = (await db.execute(stmt)).scalar_one_or_none()
    if conversation is None or conversation.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    base = select(Message).where(Message.conversation_id == conversation.id)
    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()

    stmt = (
        base.order_by(Message.created_at.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list((await db.execute(stmt)).scalars().all())
    return Paginated.create(items, total, page, page_size)


# Register the router after /health so it doesn't interfere
app.include_router(router)
