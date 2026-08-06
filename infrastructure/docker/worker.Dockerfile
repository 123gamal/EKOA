FROM ekoa-python-base:latest

# Install Worker-specific dependencies
RUN pip install --no-cache-dir \
    "celery[redis]" \
    pymupdf python-docx tiktoken \
    langchain-text-splitters \
    sqlalchemy asyncpg

# Copy source code
COPY . .

CMD ["celery", "-A", "apps.worker.main", "worker", "--loglevel=info", "--concurrency=2"]
