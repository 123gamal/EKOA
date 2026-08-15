"""Pydantic-based application settings with environment variable support."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Global configuration for the EKOA platform.

    Values are loaded from environment variables first, then from a `.env`
    file located in the current working directory.  All variable names are
    case-sensitive (i.e. ``APP_NAME`` in the env must be uppercase).
    """

    # ── Application ──────────────────────────────────────────────────────
    APP_NAME: str = "EKOA"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"  # development | production

    # ── Database ─────────────────────────────────────────────────────────
    DATABASE_URL: str = (
        "postgresql+asyncpg://ekoa_user:ekoa_secret@localhost:5432/ekoa_db"
    )

    # ── Redis ────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── Qdrant (vector store) ────────────────────────────────────────────
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333

    # ── JWT / Auth ───────────────────────────────────────────────────────
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── Connector credentials (encryption at rest) ───────────────────────
    # Fernet key (urlsafe-base64 encoded 32-byte value, e.g. the output of
    # ``cryptography.fernet.Fernet.generate_key()``) used to encrypt connector
    # access tokens (GitHub PATs) before they are persisted. This is a
    # SEPARATE secret from JWT_SECRET_KEY and must never be derived from it:
    # connector tokens live in the same database as everything else, so the
    # at-rest key is deliberately independent. Manage it like any other secret
    # (env var, secrets manager, KMS); never hardcode it in the repository.
    # Generate one with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    EKOA_FERNET_KEY: str = ""

    # ── CORS ─────────────────────────────────────────────────────────────
    # Explicit allow-list, NOT "*". FastAPI's CORSMiddleware refuses to work
    # with allow_credentials=True + "*", and browsers reject credentialed
    # cross-origin responses unless the origin is explicit. The frontend runs
    # on http://localhost:3000 in local development.
    CORS_ORIGINS: str = '["http://localhost:3000"]'

    # ── Rate limiting ──────────────────────────────────────────────────
    # Backend: "memory" (per-process, default — used in tests/local dev
    # without Docker) or "redis" (shared across replicas; set by
    # docker-compose for the api/ai services). General default applied to
    # every request (per client IP); tighter limits are applied to the auth
    # endpoints which are brute-force/spam targets.
    RATE_LIMIT_BACKEND: str = "memory"
    RATE_LIMIT_DEFAULT_LIMIT: int = 120
    RATE_LIMIT_DEFAULT_WINDOW_SECONDS: int = 60
    RATE_LIMIT_LOGIN_LIMIT: int = 10
    RATE_LIMIT_REGISTER_LIMIT: int = 10
    RATE_LIMIT_REFRESH_LIMIT: int = 30

    # ── LLM ──────────────────────────────────────────────────────────────
    LLM_PROVIDER: str = "deepseek"
    LLM_API_KEY: str = ""
    LLM_MODEL_NAME: str = "deepseek-chat"

    # ── DeepSeek (OpenAI-compatible) ─────────────────────────────────────
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_MODEL: str = "deepseek-chat"

    # ── Gemini (Google) ──────────────────────────────────────────────────
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"

    # ── Embeddings / Chunking ────────────────────────────────────────────
    EMBEDDING_MODEL_NAME: str = "all-MiniLM-L6-v2"
    CHUNK_SIZE: int = 512
    CHUNK_OVERLAP: int = 50

    # ── Email / SMTP (Phase 13 — org invites) ────────────────────────────
    # Points at a local MailHog catcher by default (see docker-compose.yml)
    # so invite emails can be sent and inspected in development without a
    # real provider. Point these at a real SMTP relay in production.
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 1025
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "no-reply@ekoa.local"
    SMTP_USE_TLS: bool = False

    # Base URL of the frontend, used to build links embedded in emails (e.g.
    # the org invite accept link).
    FRONTEND_URL: str = "http://localhost:3000"

    # ── Connectors: OAuth2 apps (Phase 14) ────────────────────────────────
    # Slack's redirect URI has no localhost exception (unlike Google), so
    # dev/test uses an ngrok HTTPS tunnel — set SLACK_OAUTH_REDIRECT_URI to
    # whatever that tunnel's current URL is.
    SLACK_CLIENT_ID: str = ""
    SLACK_CLIENT_SECRET: str = ""
    SLACK_OAUTH_REDIRECT_URI: str = "http://localhost/api/v1/connectors/oauth/slack/callback"

    GOOGLE_DRIVE_CLIENT_ID: str = ""
    GOOGLE_DRIVE_CLIENT_SECRET: str = ""
    GOOGLE_DRIVE_OAUTH_REDIRECT_URI: str = (
        "http://localhost/api/v1/connectors/oauth/google_drive/callback"
    )
    # Calendar/Sheets reuse the Drive app's client ID/secret (same Google
    # Cloud project) — just their own scope + redirect URI per connector, so
    # each OAuth grant stays minimal (a Calendar token can never read Drive
    # files, etc.) even though one app covers all three.
    GOOGLE_CALENDAR_OAUTH_REDIRECT_URI: str = (
        "http://localhost/api/v1/connectors/oauth/google_calendar/callback"
    )
    GOOGLE_SHEETS_OAUTH_REDIRECT_URI: str = (
        "http://localhost/api/v1/connectors/oauth/google_sheets/callback"
    )

    # ── Microsoft Graph (Phase 16) — Outlook + OneDrive + MS Teams ────────
    # One Azure AD app registration covers all three (different Graph scopes
    # per connector, same client credentials).
    MICROSOFT_CLIENT_ID: str = ""
    MICROSOFT_CLIENT_SECRET: str = ""
    MICROSOFT_OAUTH_REDIRECT_URI: str = (
        "http://localhost/api/v1/connectors/oauth/microsoft/callback"
    )

    # ── MCP server (Phase 8) ─────────────────────────────────────────────
    # The MCP server exposes two tenant-scoped tools (search_knowledge_base,
    # list_documents) over the Streamable HTTP transport. Clients authenticate
    # with a bearer MCP API key whose raw value is shown once at creation and
    # stored only as a SHA-256 hash. issuer/resource URLs feed AuthSettings
    # metadata (the protocol requires them); bearer verification never touches
    # the OAuth endpoint because EKOA issues its own static keys.
    MCP_HOST: str = "0.0.0.0"
    MCP_PORT: int = 8002
    MCP_STREAMABLE_HTTP_PATH: str = "/mcp"
    MCP_ISSUER_URL: str = "http://localhost:8002/"
    MCP_RESOURCE_SERVER_URL: str = "http://localhost:8002/mcp"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    def model_post_init(self, __context: object) -> None:
        """Refuse to boot with a default JWT secret outside development."""
        if (
            self.ENVIRONMENT.lower() != "development"
            and self.JWT_SECRET_KEY == "change-me-in-production"
        ):
            raise RuntimeError(
                "JWT_SECRET_KEY must be set to a strong random value when "
                "ENVIRONMENT != development."
            )
        if (
            self.ENVIRONMENT.lower() != "development"
            and not self.EKOA_FERNET_KEY
        ):
            raise RuntimeError(
                "EKOA_FERNET_KEY must be set to a Fernet key (see its "
                "docstring for generation) when ENVIRONMENT != development. "
                "Connector credentials are stored encrypted at rest and "
                "cannot be persisted without this key."
            )


def resolve_cors_origins(settings: Settings, *, allow_credentials: bool = True) -> list[str]:
    """Parse ``CORS_ORIGINS`` and fail loudly on the wildcard+credentials combo.

    ``allow_credentials=True`` combined with ``"*"`` in the origins list is an
    invalid/unsafe configuration: the browser rejects credentialed responses
    when the origin is a wildcard, so anything relying on cookies would silently
    break while appearing configured. Raising at startup makes such a regression
    impossible to ship unnoticed.
    """
    raw = settings.CORS_ORIGINS or "[]"
    try:
        origins: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"CORS_ORIGINS must be a JSON array of origin strings, got: {raw!r}"
        ) from exc

    if not isinstance(origins, list) or not all(isinstance(o, str) for o in origins):
        raise RuntimeError(
            f"CORS_ORIGINS must be a JSON array of origin strings, got: {raw!r}"
        )

    if allow_credentials and "*" in origins:
        raise RuntimeError(
            "CORS misconfiguration: allow_credentials=True cannot be combined "
            "with allow_origins containing '*'. Set CORS_ORIGINS to explicit "
            "origins (e.g. [\"http://localhost:3000\"]) in .env."
        )
    return origins


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached :class:`Settings` singleton.

    The first call reads environment variables / ``.env``; subsequent calls
    return the same instance without re-reading.
    """
    return Settings()
