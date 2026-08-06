.PHONY: help install test lint build dev-api dev-ai dev-worker dev-web dev-db clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Dependencies ─────────────────────────────────────────────────────────

install: ## Install all Python dependencies
	pip install -e packages/shared-config
	pip install -e packages/shared-types
	pip install -e packages/shared-utils
	pip install -r <(grep -h '^dependencies' apps/*/pyproject.toml 2>/dev/null || true)

install-web: ## Install Next.js frontend dependencies
	cd apps/web && npm install

# ── Testing ──────────────────────────────────────────────────────────────

test: ## Run all Python tests
	pytest tests/ -v --tb=short

test-api: ## Run API integration tests only
	pytest tests/test_api.py -v

test-agents: ## Run agent graph tests only
	pytest tests/test_agents.py -v

test-parsing: ## Run document parsing tests only
	pytest tests/test_parsing.py -v

# ── Linting ──────────────────────────────────────────────────────────────

lint: ## Lint Python code with ruff
	ruff check apps/ packages/ tests/

format: ## Format Python code with ruff
	ruff format apps/ packages/ tests/

# ── Database ─────────────────────────────────────────────────────────────

migrate: ## Generate a new Alembic migration
	cd apps/api && alembic revision --autogenerate -m "$$(date +%Y%m%d_%H%M%S)"

migrate-run: ## Apply pending migrations
	cd apps/api && alembic upgrade head

# ── Development Servers ──────────────────────────────────────────────────

dev-db: ## Start infrastructure services (PostgreSQL, Qdrant, Redis)
	docker compose -f infrastructure/docker/docker-compose.yml up -d postgres qdrant redis

dev-api: ## Start FastAPI backend
	cd apps/api && uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8000

dev-ai: ## Start AI service
	cd apps/ai && uvicorn apps.ai.main:app --reload --host 0.0.0.0 --port 8001

dev-worker: ## Start Celery worker
	cd apps/worker && celery -A apps.worker.main worker --loglevel=info --concurrency=2

dev-web: ## Start Next.js frontend
	cd apps/web && npm run dev

# ── Docker ───────────────────────────────────────────────────────────────

docker-up: ## Start all services via Docker Compose
	docker compose -f infrastructure/docker/docker-compose.yml up -d --build

docker-down: ## Stop all Docker services
	docker compose -f infrastructure/docker/docker-compose.yml down

docker-logs: ## Tail logs from Docker services
	docker compose -f infrastructure/docker/docker-compose.yml logs -f

# ── Cleanup ──────────────────────────────────────────────────────────────

clean: ## Clean Python cache, Node modules, and build artifacts
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf apps/web/.next/ apps/web/node_modules/
	rm -rf uploads/
