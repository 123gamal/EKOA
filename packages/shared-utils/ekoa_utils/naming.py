"""Naming conventions shared across services (single source of truth)."""

from __future__ import annotations

from typing import Union


def workspace_collection_name(workspace_id: Union[str, object]) -> str:
    """Return the Qdrant collection name for a workspace.

    All services (worker, AI, executor) must derive collection names through
    this helper so the naming never drifts.
    """
    return f"ekoa_{str(workspace_id)[:8]}"
