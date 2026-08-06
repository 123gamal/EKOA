from __future__ import annotations

from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from apps.api.db.engine import get_db
from apps.api.dependencies.auth import get_current_user
from apps.api.models.user import User
from apps.api.models.workspace import Workspace
from apps.api.models.document import Document
from apps.api.models.audit_log import AuditLog
from apps.api.models.workflow import WorkflowRun, Workflow
from apps.api.services import org_service

router = APIRouter(prefix="/api/v1/analytics", tags=["Analytics"])


async def _user_scope(db: AsyncSession, user_id) -> tuple[list, list]:
    """Return (org_ids, workspace_ids) the user can access."""
    orgs = await org_service.get_user_organizations(db, user_id)
    org_ids = [o.id for o in orgs]
    if not org_ids:
        return [], []
    stmt = select(Workspace.id).where(Workspace.organization_id.in_(org_ids))
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
    doc_stmt = select(Document).where(Document.workspace_id.in_(workspace_ids))
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
        .where(Workflow.workspace_id.in_(workspace_ids))
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Per-document processing statistics for the current user's workspaces."""
    _, workspace_ids = await _user_scope(db, current_user.id)
    if not workspace_ids:
        return {"documents": []}

    stmt = (
        select(Document, Workspace.name)
        .join(Workspace, Workspace.id == Document.workspace_id)
        .where(Document.workspace_id.in_(workspace_ids))
        .order_by(Document.created_at.desc())
    )
    rows = (await db.execute(stmt)).all()
    return {
        "documents": [
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
        ]
    }
