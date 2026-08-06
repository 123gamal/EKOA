from __future__ import annotations

import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from apps.api.db.engine import get_db
from apps.api.dependencies.auth import get_current_user
from apps.api.dependencies import authz
from apps.api.models.user import User
from apps.api.models.workflow import Workflow, WorkflowRun
from apps.api.services import audit_service
from apps.worker.workflow_templates import WORKFLOW_TEMPLATES, get_template
from ekoa_types.workflow import (
    WorkflowCreate,
    WorkflowResponse,
    WorkflowRunRequest,
    WorkflowRunResponse,
    WorkflowTemplate,
)

router = APIRouter(prefix="/api/v1/workflows", tags=["Workflows"])


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
        details={"name": workflow.name, "template_id": workflow.template_id, "workspace_id": str(workflow.workspace_id)}
    )
    return workflow


@router.get("/", response_model=list[WorkflowResponse])
async def list_workflows(
    workspace_id: uuid.UUID = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List workflows inside a workspace."""
    await authz.assert_can_access_workspace(workspace_id, current_user, db)
    stmt = select(Workflow).where(Workflow.workspace_id == workspace_id).order_by(desc(Workflow.created_at))
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve a single workflow instance."""
    stmt = select(Workflow).where(Workflow.id == workflow_id)
    result = await db.execute(stmt)
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    await authz.assert_can_access_workspace(workflow.workspace_id, current_user, db)
    return workflow


@router.post("/{workflow_id}/run", response_model=WorkflowRunResponse, status_code=status.HTTP_201_CREATED)
async def run_workflow(
    workflow_id: uuid.UUID,
    data: WorkflowRunRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Trigger an execution of a workflow. Enqueues the run on the Celery worker."""
    stmt = select(Workflow).where(Workflow.id == workflow_id)
    result = await db.execute(stmt)
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    await authz.assert_can_access_workspace(workflow.workspace_id, current_user, db)

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
        details={"workflow_id": str(workflow.id), "name": workflow.name}
    )

    try:
        from apps.worker.tasks import run_workflow as run_workflow_task
        run_workflow_task.delay(str(run.id))
    except Exception:
        # Worker unreachable — mark the run so the UI can retry.
        run.status = "FAILED"
        run.error = "Could not enqueue run — worker unavailable"
        run.completed_at = datetime.now(timezone.utc)
        workflow.status = "FAILED"
        await db.commit()
        await db.refresh(run)

    return run


@router.get("/{workflow_id}/runs", response_model=list[WorkflowRunResponse])
async def list_runs(
    workflow_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List execution runs for a workflow (latest first)."""
    stmt = select(Workflow).where(Workflow.id == workflow_id)
    result = await db.execute(stmt)
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    await authz.assert_can_access_workspace(workflow.workspace_id, current_user, db)

    stmt = select(WorkflowRun).where(WorkflowRun.workflow_id == workflow_id).order_by(desc(WorkflowRun.created_at))
    result = await db.execute(stmt)
    return list(result.scalars().all())
