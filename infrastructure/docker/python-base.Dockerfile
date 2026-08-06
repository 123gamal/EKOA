FROM python:3.12-slim AS python-base

WORKDIR /app

# Install system dependencies for psycopg2 / asyncpg
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Install shared packages
COPY packages/shared-config/pyproject.toml packages/shared-config/
COPY packages/shared-types/pyproject.toml packages/shared-types/
COPY packages/shared-utils/pyproject.toml packages/shared-utils/
COPY packages/shared-config/ekoa_config/ packages/shared-config/ekoa_config/
COPY packages/shared-types/ekoa_types/ packages/shared-types/ekoa_types/
COPY packages/shared-utils/ekoa_utils/ packages/shared-utils/ekoa_utils/
RUN pip install --no-cache-dir packages/shared-config \
 && pip install --no-cache-dir packages/shared-types \
 && pip install --no-cache-dir packages/shared-utils

# Pre-install heavy common deps (torch, sentence-transformers)
RUN pip install --no-cache-dir \
    sentence-transformers \
    qdrant-client \
    pydantic pydantic-settings

CMD ["echo", "Base image built"]
