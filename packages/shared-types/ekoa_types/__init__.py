"""EKOA Shared Types — Pydantic models used across all services."""

from ekoa_types.auth import LoginRequest, RegisterRequest, TokenPair
from ekoa_types.chat import AgentAction, ChatMessage, ChatRequest, ChatResponse
from ekoa_types.connector import (
    ConnectorConnectRequest,
    ConnectorHealthResponse,
    ConnectorLastSyncStatus,
    ConnectorResponse,
    ConnectorStatus,
    ConnectorSyncResponse,
    GitHubConfig,
)
from ekoa_types.conversation import ConversationResponse, MessageResponse
from ekoa_types.document import (
    DocumentBase,
    DocumentCreate,
    DocumentResponse,
    DocumentStatus,
)
from ekoa_types.organization import (
    OrganizationBase,
    OrganizationCreate,
    OrganizationResponse,
)
from ekoa_types.pagination import (
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    Paginated,
)
from ekoa_types.user import UserBase, UserCreate, UserResponse
from ekoa_types.workflow import (
    WorkflowCreate,
    WorkflowResponse,
    WorkflowRunResponse,
    WorkflowRunRequest,
    WorkflowStepSpec,
    WorkflowTemplate,
)
from ekoa_types.workspace import WorkspaceBase, WorkspaceCreate, WorkspaceResponse

__all__ = [
    # auth
    "LoginRequest",
    "RegisterRequest",
    "TokenPair",
    # chat
    "AgentAction",
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
    # connector
    "ConnectorConnectRequest",
    "ConnectorHealthResponse",
    "ConnectorLastSyncStatus",
    "ConnectorResponse",
    "ConnectorStatus",
    "ConnectorSyncResponse",
    "GitHubConfig",
    # conversation
    "ConversationResponse",
    "MessageResponse",
    # document
    "DocumentBase",
    "DocumentCreate",
    "DocumentResponse",
    "DocumentStatus",
    # organization
    "OrganizationBase",
    "OrganizationCreate",
    "OrganizationResponse",
    # pagination
    "DEFAULT_PAGE",
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "Paginated",
    # user
    "UserBase",
    "UserCreate",
    "UserResponse",
    # workflow
    "WorkflowCreate",
    "WorkflowResponse",
    "WorkflowRunResponse",
    "WorkflowRunRequest",
    "WorkflowStepSpec",
    "WorkflowTemplate",
    # workspace
    "WorkspaceBase",
    "WorkspaceCreate",
    "WorkspaceResponse",
]
