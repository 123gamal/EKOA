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

    # ── CORS ─────────────────────────────────────────────────────────────
    # Explicit allow-list, NOT "*". FastAPI's CORSMiddleware refuses to work
    # with allow_credentials=True + "*", and browsers reject credentialed
    # cross-origin responses unless the origin is explicit. The frontend runs
    # on http://localhost:3000 in local development.
    CORS_ORIGINS: str = '["http://localhost:3000"]'

    # ── Rate limiting (per process; in-memory sliding window) ────────────
    # General default applied to every request (per client IP); tighter limits
    # are applied to the auth endpoints which are brute-force/spam targets.
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
