"""Pydantic-based application settings with environment variable support."""

from __future__ import annotations

from functools import lru_cache

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
    CORS_ORIGINS: str = '["*"]'

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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached :class:`Settings` singleton.

    The first call reads environment variables / ``.env``; subsequent calls
    return the same instance without re-reading.
    """
    return Settings()
