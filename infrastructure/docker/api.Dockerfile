FROM ekoa-python-base:latest

# Install API-specific dependencies
RUN pip install --no-cache-dir \
    fastapi "uvicorn[standard]" "sqlalchemy[asyncio]" asyncpg alembic \
    "python-jose[cryptography]" bcrypt python-multipart \
    "celery[redis]" pymupdf python-docx tiktoken langchain-text-splitters

# Copy source code
COPY . .

EXPOSE 8000

# Run migrations on startup, then start uvicorn
CMD ["sh", "-c", "cd apps/api && alembic upgrade head && cd /app && uvicorn apps.api.main:app --host 0.0.0.0 --port 8000"]
