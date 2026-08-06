# EKOA Architecture Overview

## Services

EKOA is composed of **4 application services** and **3 shared packages**, backed by supporting infrastructure.

### Application Services

| Service | Directory | Technology | Purpose |
|---------|-----------|------------|---------|
| **API** | `apps/api/` | FastAPI + SQLAlchemy + Alembic | REST API gateway — authentication, JWT management, org/workspace CRUD, file uploads |
| **AI** | `apps/ai/` | FastAPI + LangGraph + SSE | AI orchestration — multi-agent RAG pipeline, streaming chat |
| **Worker** | `apps/worker/` | Celery + Redis + sentence-transformers | Background tasks — document parsing (PDF/MD/TXT), text chunking, embedding generation, Qdrant indexing |
| **Web** | `apps/web/` | Next.js 15 + TypeScript + Tailwind CSS | Frontend — login, dashboard, document management, streaming chat UI |

### Shared Packages

Shared packages live under `packages/` and are imported by the application services:

- **`packages/shared-config/`** — Centralised `pydantic-settings` configuration loaded from `.env`
- **`packages/shared-types/`** — Pydantic schemas for auth, user, organization, workspace, document, and chat
- **`packages/shared-utils/`** — Utility functions (bcrypt hashing, datetime helpers, text processing)

### Supporting Infrastructure

| Component | Purpose |
|-----------|---------|
| **PostgreSQL 16** | Primary relational database for users, orgs, workspaces, documents, sessions, audit logs |
| **Qdrant** | Vector database for document embeddings and semantic search |
| **Redis 7** | Celery broker (task queue) and caching layer |
| **Nginx** | Reverse proxy routing `/api/v1/*` → API, `/api/v1/ai/*` → AI, `/ws/*` → AI, `/*` → Web |

## Data Flow

```
User ──▶ Nginx (port 80)
            │
            ├── /api/v1/*          ──▶ API (FastAPI :8000) ──▶ PostgreSQL
            ├── /api/v1/ai/*       ──▶ AI  (FastAPI :8001) ──▶ Qdrant
            ├── /ws/*              ──▶ AI  (FastAPI :8001) ──▶ Qdrant
            └── /*                 ──▶ Web (Next.js :3000)

API ──▶ Worker (Celery) ──▶ PostgreSQL ──▶ Qdrant
                            Redis (broker)
```

## Agent Architecture (AI Service)

The LangGraph agent graph executes in 4 stages:

```
User Message
    │
    ▼
┌──────────────┐
│  Coordinator │  Analyzes query, decides routing
└──────┬───────┘
       │
       ▼
┌──────────────┐
│   Retriever  │  Searches Qdrant for relevant document chunks
└──────┬───────┘
       │
       ▼
┌──────────────┐
│   Document   │  Summarizes retrieved context
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  Synthesize  │  Builds final answer with citations
└──────┬───────┘
       │
       ▼
  Final Answer
```

## Document Ingestion Pipeline

```
Upload via API
    │
    ▼
Document metadata saved to PostgreSQL (status=PENDING)
    │
    ▼
Celery task dispatched (process_document)
    │
    ├── status → PROCESSING
    ├── Parse file (PDF via PyMuPDF, MD/TXT via stdlib)
    ├── Chunk text (RecursiveCharacterTextSplitter)
    ├── Generate embeddings (sentence-transformers, all-MiniLM-L6-v2)
    ├── Index into Qdrant (organization-isolated collections)
    └── status → INDEXED (or FAILED on error)
```

## Security

- **Password hashing**: bcrypt via the `bcrypt` library
- **JWT tokens**: HS256 via `python-jose` with unique `jti` per token
- **Token pair**: Access token (short-lived, 30 min default) + Refresh token (long-lived, 7 days default)
- **Session management**: Refresh tokens stored in `user_sessions` table with revocation support
- **Authentication**: OAuth2 Password Bearer flow via FastAPI dependency injection
