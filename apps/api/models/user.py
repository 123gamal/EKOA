from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, List
from sqlalchemy import String, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from apps.api.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from apps.api.models.org_member import OrgMember
    from apps.api.models.session import UserSession
    from apps.api.models.workspace import Workspace
    from apps.api.models.document import Document
    from apps.api.models.document_version import DocumentVersion
    from apps.api.models.workflow import Workflow
    from apps.api.models.conversation import Conversation
    from apps.api.models.connector import Connector


class User(Base, TimestampMixin):
    """User representation in the system."""
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    memberships: Mapped[List[OrgMember]] = relationship(back_populates="user", cascade="all, delete-orphan")
    sessions: Mapped[List[UserSession]] = relationship(back_populates="user", cascade="all, delete-orphan")
    created_workspaces: Mapped[List[Workspace]] = relationship(back_populates="creator")
    uploaded_documents: Mapped[List[Document]] = relationship(back_populates="uploader")
    workflows: Mapped[List[Workflow]] = relationship(back_populates="creator")
    conversations: Mapped[List[Conversation]] = relationship(back_populates="owner", cascade="all, delete-orphan")
    document_versions: Mapped[List[DocumentVersion]] = relationship(back_populates="uploader")
    connected_connectors: Mapped[List[Connector]] = relationship(
        back_populates="connector_user",
        foreign_keys="Connector.connected_by",
    )
