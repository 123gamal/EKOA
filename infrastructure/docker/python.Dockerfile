# =============================================================================
# EKOA – Python Multi-Stage Build
# Shared base + api / ai / worker targets
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 0 – Base: shared packages + lightweight common deps
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS base

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY packages/shared-config/pyproject.toml packages/shared-config/
COPY packages/shared-types/pyproject.toml packages/shared-types/
COPY packages/shared-utils/pyproject.toml packages/shared-utils/
COPY packages/shared-config/ekoa_config/ packages/shared-config/ekoa_config/
COPY packages/shared-types/ekoa_types/ packages/shared-types/ekoa_types/
COPY packages/shared-utils/ekoa_utils/ packages/shared-utils/ekoa_utils/
RUN pip install --no-cache-dir packages/shared-config \
 && pip install --no-cache-dir packages/shared-types \
 && pip install --no-cache-dir packages/shared-utils

# ---------------------------------------------------------------------------
# Stage 1 – API: FastAPI + Celery + DB / search deps
# ---------------------------------------------------------------------------
FROM base AS api

RUN pip install --no-cache-dir \
    fastapi "uvicorn[standard]" "sqlalchemy[asyncio]" asyncpg alembic \
    "python-jose[cryptography]" bcrypt python-multipart \
    "celery[redis]" pymupdf python-docx tiktoken langchain-text-splitters \
    email-validator httpx cryptography

COPY . .

EXPOSE 8000
CMD ["sh", "-c", "cd apps/api && PYTHONPATH=/app alembic upgrade head && cd /app && uvicorn apps.api.main:app --host 0.0.0.0 --port 8000"]

# ---------------------------------------------------------------------------
# Stage 2 – AI: LangGraph agent service
# ---------------------------------------------------------------------------
FROM base AS ai

RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir \
    sentence-transformers qdrant-client \
    fastapi "uvicorn[standard]" \
    langgraph langchain-core \
    sse-starlette \
    openai google-generativeai \
    "python-jose[cryptography]" "sqlalchemy[asyncio]" asyncpg \
    email-validator

COPY . .

EXPOSE 8001
CMD ["uvicorn", "apps.ai.main:app", "--host", "0.0.0.0", "--port", "8001"]

# ---------------------------------------------------------------------------
# Stage 3 – Worker: Celery background tasks
# ---------------------------------------------------------------------------
FROM base AS worker

RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir \
    sentence-transformers qdrant-client \
    "celery[redis]" \
    pymupdf python-docx tiktoken \
    langchain-text-splitters \
    sqlalchemy asyncpg psycopg2-binary httpx cryptography

COPY . .

CMD ["celery", "-A", "apps.worker.main", "worker", "--loglevel=info", "--concurrency=2"]
