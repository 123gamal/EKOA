"""Workflow-related Pydantic schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class WorkflowCreate(BaseModel):
    """Payload for creating a new workflow instance."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    template_id: str = Field(..., min_length=1, max_length=100)
    workspace_id: UUID


class WorkflowResponse(BaseModel):
    """Serialised workflow returned by API endpoints."""

    id: UUID
    name: str
    description: str | None = None
    template_id: str
    status: str = "DRAFT"
    workspace_id: UUID
    created_by: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class WorkflowRunResponse(BaseModel):
    """Serialised workflow run including real step results and logs."""

    id: UUID
    workflow_id: UUID
    status: str = "PENDING"
    steps: list | None = None
    logs: list | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    approval_status: str | None = None
    approval_step_id: str | None = None
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    approval_reason: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class WorkflowStepSpec(BaseModel):
    """Static definition of a step inside a workflow template."""

    id: str
    name: str
    type: str  # trigger | agent | vector_db | human_approval | action


class WorkflowTemplate(BaseModel):
    """Catalog entry describing a runnable workflow template."""

    id: str
    title: str
    description: str
    category: str
    steps: list[WorkflowStepSpec]


class WorkflowRunRequest(BaseModel):
    """Payload for triggering a workflow run."""

    query: str | None = None


class WorkflowApprovalRequest(BaseModel):
    """Payload for an admin's approve/reject decision on a paused run."""

    reason: str | None = Field(default=None, max_length=1000)
