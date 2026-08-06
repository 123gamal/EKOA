"""EKOA AI Service – LangGraph multi-agent orchestration with SSE streaming."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from apps.ai.graph import get_agent_graph, AgentState
from apps.ai.deps import get_current_user, assert_workspace_access_for_user
from apps.api.models.user import User
from apps.api.db.engine import get_db, get_engine
from ekoa_config.settings import get_settings
from ekoa_config.logging import setup_logging, CorrelationIdMiddleware
from ekoa_utils.naming import workspace_collection_name

setup_logging("ai")

settings = get_settings()

app = FastAPI(title="EKOA AI Service", version="0.1.0")
router = APIRouter(prefix="/api/v1/ai")

try:
    cors_origins = json.loads(settings.CORS_ORIGINS)
except (json.JSONDecodeError, TypeError):
    cors_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(CorrelationIdMiddleware)


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


def _build_initial_state(req: ChatRequest) -> AgentState:
    messages = req.history + [{"role": "user", "content": req.message}]
    return {
        "messages": messages,
        "actions": [],
        "context_chunks": [],
        "workspace_id": req.workspace_id,
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
    """Synchronous chat endpoint – returns the final answer."""
    await assert_workspace_access_for_user(current_user, req.workspace_id, db)
    graph = get_agent_graph()
    state = _build_initial_state(req)
    result = await graph.ainvoke(state)

    return ChatResponse(
        conversation_id=req.conversation_id or str(uuid.uuid4()),
        reply=result.get("final_answer") or "No answer generated.",
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
    """Streaming SSE endpoint – pushes agent actions and final answer as events."""
    await assert_workspace_access_for_user(current_user, req.workspace_id, db)
    graph = get_agent_graph()
    state = _build_initial_state(req)
    conversation_id = req.conversation_id or str(uuid.uuid4())

    async def event_generator():
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

        yield {"event": "done", "data": ""}

    return EventSourceResponse(event_generator())


# Register the router after /health so it doesn't interfere
app.include_router(router)
