"""Qdrant retrieval for the AI agent service."""

from __future__ import annotations

from functools import lru_cache
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer

from ekoa_config.settings import get_settings

settings = get_settings()


@lru_cache(maxsize=1)
def _get_qdrant() -> QdrantClient:
    return QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)


@lru_cache(maxsize=1)
def _get_embedder() -> SentenceTransformer:
    return SentenceTransformer(settings.EMBEDDING_MODEL_NAME)


def retrieve_chunks(
    query: str,
    collection_name: str = "ekoa_default",
    limit: int = 5,
) -> list[dict]:
    """Search Qdrant for chunks relevant to the query."""
    client = _get_qdrant()
    model = _get_embedder()
    query_vector = model.encode([query], show_progress_bar=False)[0].tolist()

    results = client.query_points(
        collection_name=collection_name,
        query=query_vector,
        limit=limit,
    )
    return [
        {
            "score": hit.score,
            "text": hit.payload.get("text", ""),
            "document_id": hit.payload.get("document_id", ""),
            "chunk_index": hit.payload.get("chunk_index", 0),
        }
        for hit in results.points
    ]
