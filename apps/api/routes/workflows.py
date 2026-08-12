from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select, desc

from apps.api.db.engine import get_db
from apps.api.dependencies.auth import get_current_user
from apps.api.dependencies import authz
from apps.api.models.user import User
from apps.api.models.workflow import Workflow, WorkflowRun
from apps.api.services import audit_service
from apps.worker.workflow_templates import WORKFLOW_TEMPLATES, get_template
from ekoa_config.logging import get_correlation_id, get_logger
from ekoa_types.pagination import (
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    Paginated,
)
from ekoa_types.workflow import (
    WorkflowCreate,
    WorkflowResponse,
    WorkflowApprovalRequest,
    WorkflowRunRequest,
    WorkflowRunResponse,
    WorkflowTemplate,
)

router = APIRouter(prefix="/api/v1/workflows", tags=["Workflows"])

logger = get_logger("api.routes.workflows")


async def _load_active_workflow(
    db: AsyncSession, workflow_id: uuid.UUID
) -> Workflow:
    """Load a non-deleted workflow or raise 404."""
    stmt = select(Workflow).where(
        Workflow.id == workflow_id,
        Workflow.deleted_at.is_(None),
    )
    result = await db.execute(stmt)
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return workflow


@router.get("/templates", response_model=list[WorkflowTemplate])
async def list_templates(
    current_user: User = Depends(get_current_user),
):
    """List available workflow templates from the catalog."""
    return WORKFLOW_TEMPLATES


@router.post("/", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    data: WorkflowCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a workflow instance from a template inside a workspace."""
    await authz.assert_can_access_workspace(data.workspace_id, current_user, db)
    org_id = await authz.org_id_for_workspace(db, data.workspace_id)
    if org_id is not None:
        await authz.assert_min_role(db, current_user.id, org_id, "admin")
    if get_template(data.template_id) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown workflow template: {data.template_id}"
        )

    workflow = Workflow(
        name=data.name,
        description=data.description,
        template_id=data.template_id,
        status="DRAFT",
        workspace_id=data.workspace_id,
        created_by=current_user.id
    )
    db.add(workflow)
    await db.commit()
    await db.refresh(workflow)

    await audit_service.log_action(
        db,
        user_id=current_user.id,
        action="workflow.create",
        resource_type="workflows",
        resource_id=workflow.id,
        details={"name": workflow.name, "template_id": workflow.template_id, "workspace_id": str(workflow.workspace_id)},
        organization_id=org_id,
    )
    return workflow


@router.get("/", response_model=Paginated[WorkflowResponse])
async def list_workflows(
    workspace_id: uuid.UUID = Query(...),
    page: int = Query(DEFAULT_PAGE, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Items per page"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List workflows inside a workspace (paginated, latest first)."""
    await authz.assert_can_access_workspace(workspace_id, current_user, db)

    base = select(Workflow).where(
        Workflow.workspace_id == workspace_id,
        Workflow.deleted_at.is_(None),
    )
    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()

    stmt = (
        base.order_by(desc(Workflow.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list((await db.execute(stmt)).scalars().all())
    return Paginated.create(items, total, page, page_size)


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve a single workflow instance."""
    stmt = select(Workflow).where(
        Workflow.id == workflow_id,
        Workflow.deleted_at.is_(None),
    )
    result = await db.execute(stmt)
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    await authz.assert_can_access_workspace(workflow.workspace_id, current_user, db)
    return workflow


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(
    workflow_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Soft-delete a workflow (admin role or higher). The row is kept with deleted_at set."""
    stmt = select(Workflow).where(
        Workflow.id == workflow_id,
        Workflow.deleted_at.is_(None),
    )
    result = await db.execute(stmt)
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    await authz.assert_can_access_workspace(workflow.workspace_id, current_user, db)

    org_id = await authz.org_id_for_workspace(db, workflow.workspace_id)
    if org_id is not None:
        await authz.assert_min_role(db, current_user.id, org_id, "admin")

    workflow.deleted_at = datetime.now(timezone.utc)
    db.add(workflow)
    await db.commit()

    await audit_service.log_action(
        db,
        user_id=current_user.id,
        action="workflow.delete",
        resource_type="workflows",
        resource_id=workflow.id,
        details={"name": workflow.name, "workspace_id": str(workflow.workspace_id)},
        organization_id=org_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{workflow_id}/run", response_model=WorkflowRunResponse, status_code=status.HTTP_201_CREATED)
async def run_workflow(
    workflow_id: uuid.UUID,
    data: WorkflowRunRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Trigger an execution of a workflow. Enqueues the run on the Celery worker."""
    stmt = select(Workflow).where(
        Workflow.id == workflow_id,
        Workflow.deleted_at.is_(None),
    )
    result = await db.execute(stmt)
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    await authz.assert_can_access_workspace(workflow.workspace_id, current_user, db)
    org_id = await authz.org_id_for_workspace(db, workflow.workspace_id)
    if org_id is not None:
        await authz.assert_min_role(db, current_user.id, org_id, "admin")

    run = WorkflowRun(
        workflow_id=workflow.id,
        status="PENDING",
        input_json=data.model_dump() if data else {},
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    workflow.status = "PENDING"
    db.add(workflow)
    await db.commit()

    await audit_service.log_action(
        db,
        user_id=current_user.id,
        action="workflow.run",
        resource_type="workflow_runs",
        resource_id=run.id,
        details={"workflow_id": str(workflow.id), "name": workflow.name},
        organization_id=org_id,
    )

    try:
        from apps.worker.tasks import run_workflow as run_workflow_task
        run_workflow_task.delay(str(run.id), correlation_id=get_correlation_id())
    except Exception:
        # Worker unreachable — mark the run so the UI can retry.
        run.status = "FAILED"
        run.error = "Could not enqueue run — worker unavailable"
        run.completed_at = datetime.now(timezone.utc)
        workflow.status = "FAILED"
        await db.commit()
        await db.refresh(run)

    return run


@router.get("/{workflow_id}/runs", response_model=Paginated[WorkflowRunResponse])
async def list_runs(
    workflow_id: uuid.UUID,
    page: int = Query(DEFAULT_PAGE, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Items per page"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List execution runs for a workflow (paginated, latest first)."""
    stmt = select(Workflow).where(
        Workflow.id == workflow_id,
        Workflow.deleted_at.is_(None),
    )
    result = await db.execute(stmt)
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    await authz.assert_can_access_workspace(workflow.workspace_id, current_user, db)

    base = select(WorkflowRun).where(WorkflowRun.workflow_id == workflow_id)
    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()

    stmt = (
        base.order_by(desc(WorkflowRun.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list((await db.execute(stmt)).scalars().all())
    return Paginated.create(items, total, page, page_size)


# ── Human-in-the-loop approval ───────────────────────────────────────────────


async def _load_pending_run(
    db: AsyncSession, workflow: Workflow, run_id: uuid.UUID
) -> WorkflowRun:
    """Load the paused run for a workflow or raise 404/409."""
    stmt = select(WorkflowRun).where(
        WorkflowRun.id == run_id,
        WorkflowRun.workflow_id == workflow.id,
    )
    result = await db.execute(stmt)
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    if run.status != "AWAITING_APPROVAL" or run.approval_status != "PENDING":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run is not awaiting approval",
        )
    return run


def _decide_step(run: WorkflowRun, current_user: User, decision: str, reason: str | None) -> None:
    """Mark the pending approval step as decided and append a log line."""
    # Deep-copy the JSON steps: SQLAlchemy's JSON column does not track in-place
    # mutations, and a shallow ``list(...)`` copy of the loaded list compares
    # equal after the inner dicts are mutated, so the UPDATE would be skipped.
    steps = copy.deepcopy(run.steps or [])
    decided_by = current_user.full_name or str(current_user.id)
    for s in steps:
        if s.get("id") == run.approval_step_id:
            if decision == "approved":
                s["status"] = "completed"
                s["output"] = f"Approved by {decided_by}" + (f" - {reason}" if reason else "")
            else:
                s["status"] = "rejected"
                s["output"] = f"Rejected by {decided_by}" + (f" - {reason}" if reason else "")
            s["data"] = {
                **(s.get("data") or {}),
                "decision": decision,
                "decided_by": str(current_user.id),
                "reason": reason,
            }
    logs = copy.deepcopy(run.logs or [])
    logs.append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "level": "info",
        "message": f"Human Approval: {decision} by {decided_by}",
    })
    run.steps = steps
    run.logs = logs


async def _dispatch_audit_step(
    db: AsyncSession, workflow: Workflow, run: WorkflowRun
) -> None:
    """Execute the remaining Audit Log Dispatch step after approval (compliance template).

    Mirrors the worker's step-4 behaviour so the audit row produced after an
    approval is identical in shape to the one the worker would have written had
    the run completed without pausing.
    """
    steps = list(run.steps or [])
    by_id = {s.get("id"): s for s in steps}
    s3 = by_id.get("s3") or {}
    s1 = by_id.get("s1") or {}
    findings = (s3.get("data") or {}).get("findings") or (by_id.get("s2") or {}).get("data") or {}
    documents_scanned = (s1.get("data") or {}).get("documents", 0)

    audit = await audit_service.log_action(
        db,
        user_id=workflow.created_by,
        action="workflow.compliance_audit",
        resource_type="workflows",
        resource_id=workflow.id,
        details={
            "run_id": str(run.id),
            "workspace_id": str(workflow.workspace_id),
            "verdict": "APPROVED",
            "findings": findings,
            "documents_scanned": documents_scanned,
        },
    )

    spec = {"id": "s4", "name": "Audit Log Dispatch", "type": "action"}
    tmpl = get_template(workflow.template_id)
    if tmpl:
        for s in tmpl.get("steps", []):
            if s["id"] == "s4":
                spec = s
                break
    steps.append({
        **spec,
        "status": "completed",
        "duration_ms": 0,
        "output": f"Recorded immutably in Audit Log (id {str(audit.id)[:8]})",
        "data": {"audit_log_id": str(audit.id)},
    })
    run.steps = steps


async def _assert_admin_org(db: AsyncSession, current_user: User, workflow: Workflow) -> None:
    await authz.assert_can_access_workspace(workflow.workspace_id, current_user, db)
    org_id = await authz.org_id_for_workspace(db, workflow.workspace_id)
    if org_id is not None:
        await authz.assert_min_role(db, current_user.id, org_id, "admin")


@router.post("/{workflow_id}/runs/{run_id}/approve", response_model=WorkflowRunResponse)
async def approve_run(
    workflow_id: uuid.UUID,
    run_id: uuid.UUID,
    data: WorkflowApprovalRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Approve a paused run: records the decision, resumes the remaining steps, completes it."""
    workflow = await _load_active_workflow(db, workflow_id)
    await _assert_admin_org(db, current_user, workflow)
    run = await _load_pending_run(db, workflow, run_id)

    reason = data.reason if data else None
    run.approval_status = "APPROVED"
    run.approved_by = current_user.id
    run.approved_at = datetime.now(timezone.utc)
    run.approval_reason = reason
    _decide_step(run, current_user, "approved", reason)
    await _dispatch_audit_step(db, workflow, run)

    run.status = "COMPLETED"
    run.completed_at = datetime.now(timezone.utc)
    workflow.status = "COMPLETED"
    await db.commit()
    await db.refresh(run)

    await audit_service.log_action(
        db,
        user_id=current_user.id,
        action="workflow.approve",
        resource_type="workflow_runs",
        resource_id=run.id,
        details={
            "workflow_id": str(workflow.id),
            "name": workflow.name,
            "approval_step_id": run.approval_step_id,
            "reason": reason,
        },
        organization_id=await authz.org_id_for_workspace(db, workflow.workspace_id),
    )
    logger.info(
        "workflow_run_approved",
        extra={
            "run_id": str(run.id),
            "workflow_id": str(workflow.id),
            "workspace_id": str(workflow.workspace_id),
            "approved_by": str(current_user.id),
            "reason": reason,
        },
    )
    return run


@router.post("/{workflow_id}/runs/{run_id}/reject", response_model=WorkflowRunResponse)
async def reject_run(
    workflow_id: uuid.UUID,
    run_id: uuid.UUID,
    data: WorkflowApprovalRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reject a paused run: records the decision and terminates the run."""
    workflow = await _load_active_workflow(db, workflow_id)
    await _assert_admin_org(db, current_user, workflow)
    run = await _load_pending_run(db, workflow, run_id)

    reason = data.reason if data else None
    run.approval_status = "REJECTED"
    run.approved_by = current_user.id
    run.approved_at = datetime.now(timezone.utc)
    run.approval_reason = reason
    _decide_step(run, current_user, "rejected", reason)

    run.status = "REJECTED"
    run.completed_at = datetime.now(timezone.utc)
    workflow.status = "REJECTED"
    await db.commit()
    await db.refresh(run)

    await audit_service.log_action(
        db,
        user_id=current_user.id,
        action="workflow.reject",
        resource_type="workflow_runs",
        resource_id=run.id,
        details={
            "workflow_id": str(workflow.id),
            "name": workflow.name,
            "approval_step_id": run.approval_step_id,
            "reason": reason,
        },
        organization_id=await authz.org_id_for_workspace(db, workflow.workspace_id),
    )
    logger.warning(
        "workflow_run_rejected",
        extra={
            "run_id": str(run.id),
            "workflow_id": str(workflow.id),
            "workspace_id": str(workflow.workspace_id),
            "rejected_by": str(current_user.id),
            "reason": reason,
        },
    )
    return run
