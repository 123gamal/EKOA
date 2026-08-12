"""Qdrant retrieval for the AI agent service."""

from __future__ import annotations

import hashlib
import json
import threading
from functools import lru_cache
from qdrant_client import QdrantClient
from qdrant_client.http import models as qdrant_models
from sentence_transformers import SentenceTransformer

from ekoa_config.logging import get_logger
from ekoa_config.redis_client import get_sync_redis
from ekoa_config.settings import get_settings

settings = get_settings()
logger = get_logger("ai.retriever")

# SentenceTransformer.encode() is not safe to call concurrently from multiple
# threads: the underlying HuggingFace tokenizers library runs its own internal
# thread pool and can deadlock when invoked from several Python threads at
# once (the well-known TOKENIZERS_PARALLELISM issue). Since retrieve_chunks is
# now dispatched via asyncio.to_thread and can genuinely run concurrently
# across requests, serialize access to the shared embedder instance.
_embed_lock = threading.Lock()

# Redis is a pure optimization here: query embeddings and search results are
# cached, but any Redis error falls through to computing normally rather than
# failing the request. Embeddings are cached globally (embedding of a given
# text string leaks nothing tenant-specific); search results are cached per
# workspace so tenant isolation is preserved.
_EMBEDDING_CACHE_TTL_SECONDS = 60 * 60
_SEARCH_CACHE_TTL_SECONDS = 5 * 60


@lru_cache(maxsize=1)
def _get_qdrant() -> QdrantClient:
    return QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)


@lru_cache(maxsize=1)
def _get_embedder() -> SentenceTransformer:
    return SentenceTransformer(settings.EMBEDDING_MODEL_NAME)


def _embed_query_cached(query: str) -> list[float]:
    """Encode a query, transparently caching the result in Redis by text hash."""
    cache_key = f"embcache:{hashlib.sha256(query.encode('utf-8')).hexdigest()}"
    try:
        cached = get_sync_redis().get(cache_key)
        if cached is not None:
            return json.loads(cached)
    except Exception as exc:  # noqa: BLE001
        logger.warning("embedding_cache_read_failed", extra={"error": str(exc)})

    with _embed_lock:
        vector = _get_embedder().encode([query], show_progress_bar=False)[0].tolist()

    try:
        get_sync_redis().set(cache_key, json.dumps(vector), ex=_EMBEDDING_CACHE_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001
        logger.warning("embedding_cache_write_failed", extra={"error": str(exc)})

    return vector


def _tenant_filter(organization_id: str | None, workspace_id: str | None) -> qdrant_models.Filter | None:
    """Build a Qdrant filter pinning results to a tenant (organization + workspace).

    Defense-in-depth: even though each workspace already has its own collection
    (ekoa_{workspace_id[:8]}), every indexed point also carries
    ``organization_id`` and ``workspace_id`` in its payload, and retrieval must
    match on both so a misconfigured/leaked collection name can never leak
    another tenant's content.
    """
    must: list[qdrant_models.FieldCondition] = []
    if organization_id:
        must.append(
            qdrant_models.FieldCondition(
                key="organization_id",
                match=qdrant_models.MatchValue(value=str(organization_id)),
            )
        )
    if workspace_id:
        must.append(
            qdrant_models.FieldCondition(
                key="workspace_id",
                match=qdrant_models.MatchValue(value=str(workspace_id)),
            )
        )
    if not must:
        return None
    return qdrant_models.Filter(must=must)


def _search_cache_key(
    query: str, collection_name: str, limit: int, workspace_id: str | None
) -> str:
    digest = hashlib.sha256(f"{collection_name}:{limit}:{query}".encode("utf-8")).hexdigest()
    return f"searchcache:{workspace_id or 'none'}:{digest}"


def retrieve_chunks(
    query: str,
    collection_name: str = "ekoa_default",
    limit: int = 5,
    organization_id: str | None = None,
    workspace_id: str | None = None,
) -> list[dict]:
    """Search Qdrant for chunks relevant to the query, scoped to the tenant.

    Wrapped by a short-TTL, workspace-scoped Redis cache: identical repeated
    queries within a workspace skip both the embedding call and the Qdrant
    search. Any Redis error is treated as a cache miss, never a failure.
    """
    cache_key = _search_cache_key(query, collection_name, limit, workspace_id)
    try:
        cached = get_sync_redis().get(cache_key)
        if cached is not None:
            return json.loads(cached)
    except Exception as exc:  # noqa: BLE001
        logger.warning("search_cache_read_failed", extra={"error": str(exc)})

    client = _get_qdrant()
    query_vector = _embed_query_cached(query)

    results = client.query_points(
        collection_name=collection_name,
        query=query_vector,
        query_filter=_tenant_filter(organization_id, workspace_id),
        limit=limit,
    )
    chunks = [
        {
            "score": hit.score,
            "text": hit.payload.get("text", ""),
            "document_id": hit.payload.get("document_id", ""),
            "chunk_index": hit.payload.get("chunk_index", 0),
        }
        for hit in results.points
    ]

    try:
        get_sync_redis().set(cache_key, json.dumps(chunks), ex=_SEARCH_CACHE_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001
        logger.warning("search_cache_write_failed", extra={"error": str(exc)})

    return chunks
