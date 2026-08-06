# Enterprise Knowledge Operations Assistant (EKOA)

EKOA is an AI-first enterprise knowledge platform integrating Retrieval-Augmented Generation (RAG), multi-agent orchestration (LangGraph), and enterprise-grade security.

## Architecture

| Service | Directory | Technology | Purpose |
|---------|-----------|------------|---------|
| **API** | `apps/api/` | FastAPI + SQLAlchemy | REST backend — auth, org/workspace CRUD, document upload |
| **AI** | `apps/ai/` | LangGraph + FastAPI | Multi-agent RAG orchestration with SSE streaming |
| **Worker** | `apps/worker/` | Celery + Redis | Background document ingestion, chunking, embeddings |
| **Web** | `apps/web/` | Next.js 15 + Tailwind | UI — dashboard, document manager, streaming chat |

**Infrastructure**: PostgreSQL 16, Qdrant (vectors), Redis (cache/broker), Nginx (gateway)

## Quick Start

### 1. Start infrastructure

```bash
docker compose -f infrastructure/docker/docker-compose.yml up -d postgres qdrant redis
```

### 2. Install Python packages

```bash
pip install -e packages/shared-config
pip install -e packages/shared-types
pip install -e packages/shared-utils
```

### 3. Run database migrations

```bash
cd apps/api
alembic upgrade head
```

### 4. Start development servers

**API backend** (terminal 1):
```bash
cd apps/api && uvicorn apps.api.main:app --reload --port 8000
```

**AI service** (terminal 2):
```bash
cd apps/ai && uvicorn apps.ai.main:app --reload --port 8001
```

**Celery worker** (terminal 3):
```bash
cd apps/worker && celery -A apps.worker.main worker --loglevel=info
```

**Frontend** (terminal 4):
```bash
cd apps/web && npm install && npm run dev
```

### 5. Access the application

- **Web UI**: http://localhost:3000
- **API docs**: http://localhost:8000/docs
- **AI health**: http://localhost:8001/health
- **Qdrant dashboard**: http://localhost:6333/dashboard

## Testing

```bash
# Run all Python tests
pytest tests/ -v

# Run specific test suites
pytest tests/test_api.py -v       # API integration tests
pytest tests/test_agents.py -v    # LangGraph agent tests
pytest tests/test_parsing.py -v   # Document parsing tests
```

## Docker (Full Stack)

```bash
# Build and start all services
docker compose -f infrastructure/docker/docker-compose.yml up -d --build

# View logs
docker compose -f infrastructure/docker/docker-compose.yml logs -f

# Stop everything
docker compose -f infrastructure/docker/docker-compose.yml down
```

## Project Structure

```
ekoa/
├── apps/
│   ├── api/           # FastAPI REST service
│   ├── ai/            # LangGraph agent service
│   ├── worker/        # Celery background worker
│   └── web/           # Next.js 15 frontend
├── packages/
│   ├── shared-config/ # Centralised settings (pydantic-settings)
│   ├── shared-types/  # Shared Pydantic schemas
│   └── shared-utils/  # Utility functions
├── infrastructure/
│   ├── docker/        # Docker Compose & Dockerfiles
│   └── nginx/         # Nginx reverse proxy config
├── tests/             # Integration & unit tests
├── docs/              # Architecture documentation
└── Makefile           # Common dev tasks
```
