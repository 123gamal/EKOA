from __future__ import annotations

import math
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select

from apps.api.db.engine import get_db
from apps.api.dependencies.auth import get_current_user
from apps.api.models.user import User
from apps.api.models.workspace import Workspace
from apps.api.models.document import Document
from apps.api.models.audit_log import AuditLog
from apps.api.models.ai_call_log import AiCallLog
from apps.api.models.workflow import WorkflowRun, Workflow
from apps.api.services import org_service
from ekoa_types.pagination import (
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    Paginated,
)

router = APIRouter(prefix="/api/v1/analytics", tags=["Analytics"])


async def _user_scope(db: AsyncSession, user_id) -> tuple[list, list]:
    """Return (org_ids, workspace_ids) the user can access (soft-deleted excluded)."""
    orgs = await org_service.get_user_organizations(db, user_id)
    org_ids = [o.id for o in orgs]
    if not org_ids:
        return [], []
    stmt = select(Workspace.id).where(
        Workspace.organization_id.in_(org_ids),
        Workspace.deleted_at.is_(None),
    )
    result = await db.execute(stmt)
    return org_ids, list(result.scalars().all())


@router.get("/overview")
async def analytics_overview(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Real-time operational analytics derived from live database state."""
    org_ids, workspace_ids = await _user_scope(db, current_user.id)

    if not workspace_ids:
        return {
            "organizations": len(org_ids),
            "workspaces": 0,
            "documents": 0,
            "documents_by_status": {},
            "chunks": 0,
            "success_rate": 0.0,
            "workflow_runs": {},
            "uploads_last_7_days": [],
            "recent_runs": [],
            "recent_activity": [],
        }

    # Documents
    doc_stmt = select(Document).where(
        Document.workspace_id.in_(workspace_ids),
        Document.deleted_at.is_(None),
    )
    docs = list((await db.execute(doc_stmt)).scalars().all())
    by_status: dict[str, int] = {}
    for d in docs:
        by_status[d.status] = by_status.get(d.status, 0) + 1
    total_chunks = sum(d.chunk_count for d in docs)
    success_rate = round((by_status.get("INDEXED", 0) / len(docs)), 3) if docs else 0.0

    # Uploads per day for the last 7 days
    today = datetime.now(timezone.utc).date()
    bucket: dict[str, int] = {}
    for i in range(6, -1, -1):
        bucket[(today - timedelta(days=i)).isoformat()] = 0
    for d in docs:
        day = d.created_at.date() if d.created_at.tzinfo is not None else d.created_at.date()
        key = day.isoformat()
        if key in bucket:
            bucket[key] += 1
    uploads_7d = [{"date": k, "count": v} for k, v in bucket.items()]

    # Workflow runs in scope
    run_stmt = (
        select(WorkflowRun)
        .join(Workflow, Workflow.id == WorkflowRun.workflow_id)
        .where(
            Workflow.workspace_id.in_(workspace_ids),
            Workflow.deleted_at.is_(None),
        )
    )
    runs = list((await db.execute(run_stmt)).scalars().all())
    run_by_status: dict[str, int] = {}
    for r in runs:
        run_by_status[r.status] = run_by_status.get(r.status, 0) + 1

    recent_runs = [
        {
            "workflow_id": str(r.workflow_id),
            "status": r.status,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        }
        for r in sorted(runs, key=lambda x: x.created_at, reverse=True)[:5]
    ]

    # Recent audit activity (scoped to the current user's own actions)
    audit_stmt = (
        select(AuditLog)
        .where(
            AuditLog.user_id == current_user.id,
            AuditLog.action.in_(["document.upload", "workflow.run", "workflow.compliance_audit", "organization.create", "workspace.create"])
        )
        .order_by(AuditLog.created_at.desc())
        .limit(8)
    )
    recent_activity = [
        {"action": a.action, "resource_type": a.resource_type, "details": a.details, "created_at": a.created_at.isoformat()}
        for a in (await db.execute(audit_stmt)).scalars().all()
    ]

    return {
        "organizations": len(org_ids),
        "workspaces": len(workspace_ids),
        "documents": len(docs),
        "documents_by_status": by_status,
        "chunks": total_chunks,
        "success_rate": success_rate,
        "workflow_runs": run_by_status,
        "uploads_last_7_days": uploads_7d,
        "recent_runs": recent_runs,
        "recent_activity": recent_activity,
    }


@router.get("/documents")
async def analytics_documents(
    page: int = Query(DEFAULT_PAGE, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Items per page"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Per-document processing statistics for the current user's workspaces (paginated, latest first)."""
    _, workspace_ids = await _user_scope(db, current_user.id)
    if not workspace_ids:
        return {"items": [], "total": 0, "page": page, "page_size": page_size, "pages": 0}

    base = (
        select(Document, Workspace.name)
        .join(Workspace, Workspace.id == Document.workspace_id)
        .where(
            Document.workspace_id.in_(workspace_ids),
            Document.deleted_at.is_(None),
        )
    )
    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()

    stmt = base.order_by(Document.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(stmt)).all()
    return {
        "items": [
            {
                "id": str(doc.id),
                "title": doc.title,
                "status": doc.status,
                "content_type": doc.content_type,
                "chunk_count": doc.chunk_count,
                "workspace": ws_name,
                "created_at": doc.created_at.isoformat(),
            }
            for doc, ws_name in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": math.ceil(total / page_size) if total else 0,
    }


# ── Model performance (FR-1000) ───────────────────────────────────────────────


def _percentile(sorted_values: list[int], pct: float) -> int | None:
    """Nearest-rank percentile over a sorted list (None when empty)."""
    n = len(sorted_values)
    if n == 0:
        return None
    return sorted_values[max(0, int(math.ceil(pct * n / 100)) - 1)]


@router.get("/model-performance")
async def model_performance(
    workspace_id: str | None = Query(None, description="Restrict to one workspace"),
    days: int = Query(7, ge=1, le=90, description="Lookback window in days"),
    page: int = Query(DEFAULT_PAGE, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Items per page"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Real AI-call telemetry aggregated from ``ai_call_logs`` (FR-1000).

    Latency / token usage / degraded, guardrail, and citation-drop rates are
    computed from actual persisted chat calls in the caller's workspaces —
    nothing here is fabricated. ``summary.est_cost_usd`` is explicitly an
    ESTIMATE derived from token counts × list prices (see ekoa_utils.cost),
    not a billed figure.
    """
    org_ids, workspace_ids = await _user_scope(db, current_user.id)
    if not workspace_ids:
        return {
            "summary": {
                "calls": 0,
                "avg_latency_ms": None,
                "p95_latency_ms": None,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "degraded_rate": 0.0,
                "guardrail_trigger_rate": 0.0,
                "citation_drop_rate": 0.0,
                "est_cost_usd": 0.0,
                "cost_is_estimate": True,
                "providers": {},
            },
            "daily": [],
            "recent_calls": {"items": [], "total": 0, "page": page, "page_size": page_size, "pages": 0},
        }

    if workspace_id is not None:
        try:
            ws_uuid = uuid.UUID(workspace_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid workspace_id"
            )
        if ws_uuid not in workspace_ids:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found"
            )
        workspace_ids = [ws_uuid]

    since = datetime.now(timezone.utc) - timedelta(days=days)
    base = select(AiCallLog).where(
        AiCallLog.workspace_id.in_(workspace_ids),
        AiCallLog.created_at >= since,
    )
    calls = list(
        (await db.execute(base.order_by(AiCallLog.created_at.desc()))).scalars().all()
    )
    total = len(calls)

    latencies = sorted(c.latency_ms for c in calls if c.latency_ms is not None)
    avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else None
    p95_latency = _percentile(latencies, 95)

    prompt_tokens = sum(c.prompt_tokens or 0 for c in calls)
    completion_tokens = sum(c.completion_tokens or 0 for c in calls)
    total_tokens = sum(c.total_tokens or 0 for c in calls)

    def _rate(getter) -> float:
        return round(sum(1 for c in calls if getter(c)) / total, 4) if total else 0.0

    est_cost = sum(float(c.cost_estimate) for c in calls if c.cost_estimate is not None)
    provider_counts = Counter(c.provider or "fallback" for c in calls)

    # Daily buckets (token usage + latency over time). Buckets always cover the
    # last ``days`` days so the chart doesn't look truncated on quiet days.
    today = datetime.now(timezone.utc).date()
    bucket: dict[str, dict] = {}
    for i in range(days - 1, -1, -1):
        key = (today - timedelta(days=i)).isoformat()
        bucket[key] = {
            "date": key,
            "calls": 0,
            "avg_latency_ms": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "est_cost_usd": 0.0,
        }
    for c in calls:
        created = c.created_at
        if created is not None and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        key = (created.date() if created else today).isoformat()
        if key in bucket:
            b = bucket[key]
            b["calls"] += 1
            b["prompt_tokens"] += c.prompt_tokens or 0
            b["completion_tokens"] += c.completion_tokens or 0
            b["total_tokens"] += c.total_tokens or 0
            b["est_cost_usd"] = round(
                b["est_cost_usd"] + (float(c.cost_estimate) if c.cost_estimate is not None else 0.0),
                6,
            )
    day_latencies: dict[str, list[int]] = {}
    for c in calls:
        created = c.created_at
        if created is not None and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        key = (created.date() if created else today).isoformat()
        if c.latency_ms is not None:
            day_latencies.setdefault(key, []).append(c.latency_ms)
    for key, values in day_latencies.items():
        if values:
            bucket[key]["avg_latency_ms"] = round(sum(values) / len(values), 2)

    daily = list(bucket.values())

    start_idx = (page - 1) * page_size
    page_items = calls[start_idx : start_idx + page_size]
    items = [
        {
            "id": str(c.id),
            "provider": c.provider,
            "model": c.model,
            "latency_ms": c.latency_ms,
            "prompt_tokens": c.prompt_tokens,
            "completion_tokens": c.completion_tokens,
            "total_tokens": c.total_tokens,
            "degraded": c.degraded,
            "guardrail_triggered": c.guardrail_triggered,
            "citations_dropped": c.citations_dropped,
            "cost_estimate": float(c.cost_estimate) if c.cost_estimate is not None else None,
            "workspace_id": str(c.workspace_id),
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in page_items
    ]

    return {
        "summary": {
            "calls": total,
            "avg_latency_ms": avg_latency,
            "p95_latency_ms": p95_latency,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "degraded_rate": _rate(lambda c: c.degraded),
            "guardrail_trigger_rate": _rate(lambda c: c.guardrail_triggered),
            "citation_drop_rate": _rate(lambda c: c.citations_dropped),
            "est_cost_usd": round(est_cost, 6),
            "cost_is_estimate": True,
            "providers": dict(provider_counts),
        },
        "daily": daily,
        "recent_calls": Paginated.create(items, total, page, page_size),
    }
