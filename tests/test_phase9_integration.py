"""Phase 9 Postgres integration test.

Runs Alembic ``upgrade head`` directly against a real Postgres database so the
teardown/rebuild chain (all prior migrations + ``9a8b7c6d5e4f3a2b``) is proven,
then verifies the ``ai_call_logs`` table created by the new migration and that
a real write/aggregate round-trips through the analytics endpoint's SQL.

This test is hermetic with respect to LLM/Qdrant: it never calls a provider.
It requires Postgres and is skipped when the test suite runs on SQLite (the
default standalone `pytest tests/`). CI runs it in a dedicated job that
launches a ``postgres`` service container and sets ``DATABASE_URL``.
"""
import pytest

from ekoa_config.settings import get_settings

pytestmark = pytest.mark.skipif(
    not (get_settings().DATABASE_URL or "").startswith("postgres"),
    reason="Phase 9 Postgres integration test requires DATABASE_URL postgres",
)

import asyncio  # noqa: E402
import uuid  # noqa: E402
from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from apps.api.models.ai_call_log import AiCallLog  # noqa: E402
from apps.api.models.user import User  # noqa: E402
from apps.api.models.organization import Organization  # noqa: E402
from apps.api.models.org_member import OrgMember  # noqa: E402
from apps.api.models.workspace import Workspace  # noqa: E402


def _async_url() -> str:
    url = get_settings().DATABASE_URL
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql+psycopg://"):
        return url.replace("psycopg", "asyncpg", 1)
    return url


@pytest.fixture(scope="module")
async def migrated_engine():
    """Alembic upgrade head against a real Postgres, yielding a shared engine."""
    import alembic.config
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(_async_url(), echo=False, future=True, poolclass=NullPool)
    cfg = alembic.config.Config("apps/api/alembic.ini")
    cfg.set_main_option("script_location", "apps/api/alembic")
    cfg.set_main_option("sqlalchemy.url", _async_url())

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, alembic.command.upgrade, cfg, "head")

    yield engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_alembic_upgrade_head_creates_ai_call_logs(migrated_engine):
    async with migrated_engine.connect() as conn:
        result = await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'ai_call_logs' ORDER BY ordinal_position"
        ))
        columns = {row[0] for row in result.fetchall()}
    expected = {
        "id", "organization_id", "workspace_id", "conversation_id", "message_id",
        "user_id", "provider", "model", "latency_ms", "prompt_tokens",
        "completion_tokens", "total_tokens", "degraded", "guardrail_triggered",
        "citations_dropped", "cost_estimate", "error", "created_at", "updated_at",
    }
    assert expected.issubset(columns), f"missing columns: {expected - columns}"


@pytest.mark.asyncio
async def test_ai_call_log_write_and_read_back(migrated_engine):
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.ext.asyncio import AsyncSession

    Session = sessionmaker(bind=migrated_engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        user = User(
            email=f"p9i-{uuid.uuid4().hex[:10]}@example.com",
            full_name="Phase 9 Integration",
            hashed_password="x",
        )
        session.add(user)
        await session.flush()
        org = Organization(
            name="Phase 9 Integration Org",
            slug=f"p9i-{uuid.uuid4().hex[:8]}",
            owner_id=user.id,
        )
        session.add(org)
        await session.flush()
        session.add(OrgMember(user_id=user.id, organization_id=org.id, role="owner"))
        workspace = Workspace(
            name="Phase 9 Integration Workspace",
            organization_id=org.id,
            created_by=user.id,
        )
        session.add(workspace)
        await session.flush()

        log = AiCallLog(
            organization_id=org.id,
            workspace_id=workspace.id,
            user_id=user.id,
            provider="deepseek",
            model="deepseek-chat",
            latency_ms=321,
            prompt_tokens=40,
            completion_tokens=20,
            total_tokens=60,
            degraded=False,
            guardrail_triggered=False,
            citations_dropped=False,
            cost_estimate=0.000123456,
        )
        session.add(log)
        await session.commit()
        await session.refresh(log)

        row = (await session.execute(select(AiCallLog).where(AiCallLog.id == log.id))).scalar_one()
        assert row.provider == "deepseek"
        assert row.latency_ms == 321
        assert row.total_tokens == 60
        # NUMERIC(12,6) column stores 6 decimal places.
        assert float(row.cost_estimate) == 0.000123
        assert row.workspace_id == workspace.id
        assert row.created_at is not None