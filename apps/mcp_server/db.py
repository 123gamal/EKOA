"""Injectable DB session factory for the MCP server process.

The MCP server shares the platform database with the API and worker, but its
process may legitimately want a different session factory in tests (e.g. the
test-suite's in-memory SQLite engine). ``set_mcp_session_factory`` lets tests
point every lookup at the same database the API tests are writing to.
"""

from __future__ import annotations

from typing import Any

from apps.api.db.engine import get_session_factory

_factory: Any = None


def set_mcp_session_factory(factory: Any) -> None:
    """Override the session factory used by the MCP server (test hook)."""
    global _factory
    _factory = factory


def get_mcp_session_factory() -> Any:
    """Return the MCP server's session factory, lazily defaulting to the app one."""
    global _factory
    if _factory is None:
        _factory = get_session_factory()
    return _factory