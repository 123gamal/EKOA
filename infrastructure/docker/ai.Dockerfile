FROM ekoa-python-base:latest

# Install AI-specific dependencies
RUN pip install --no-cache-dir \
    fastapi "uvicorn[standard]" \
    langgraph langchain-core \
    sse-starlette \
    openai google-generativeai

# Copy source code
COPY . .

EXPOSE 8001

CMD ["uvicorn", "apps.ai.main:app", "--host", "0.0.0.0", "--port", "8001"]
