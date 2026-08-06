"""Embedding generation and Qdrant vector store operations."""

from __future__ import annotations

from functools import lru_cache
from uuid import UUID, uuid5

from qdrant_client import QdrantClient
from qdrant_client.http import models
from sentence_transformers import SentenceTransformer

from ekoa_config.settings import get_settings

settings = get_settings()


@lru_cache(maxsize=1)
def get_embedding_model() -> SentenceTransformer:
    return SentenceTransformer(settings.EMBEDDING_MODEL_NAME)


@lru_cache(maxsize=1)
def get_qdrant_client() -> QdrantClient:
    return QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)


def generate_embeddings(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for a list of text chunks."""
    model = get_embedding_model()
    embeddings = model.encode(texts, show_progress_bar=False)
    return embeddings.tolist()


def ensure_collection(collection_name: str, vector_size: int = 384) -> None:
    """Create a Qdrant collection if it doesn't exist."""
    client = get_qdrant_client()
    collections = client.get_collections().collections
    if not any(c.name == collection_name for c in collections):
        client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(
                size=vector_size,
                distance=models.Distance.COSINE,
            ),
        )


def index_chunks(
    collection_name: str,
    document_id: UUID,
    chunks: list[str],
    embeddings: list[list[float]],
) -> int:
    """Index document chunks into a Qdrant collection."""
    client = get_qdrant_client()
    points = []
    for i, (chunk_text, embedding) in enumerate(zip(chunks, embeddings)):
        point_id = uuid5(UUID(str(document_id)), str(i))
        points.append(
            models.PointStruct(
                id=str(point_id),
                vector=embedding,
                payload={
                    "document_id": str(document_id),
                    "chunk_index": i,
                    "text": chunk_text,
                },
            )
        )
    client.upsert(collection_name=collection_name, points=points)
    return len(points)


def search_collection(
    collection_name: str,
    query_text: str,
    limit: int = 5,
) -> list[dict]:
    """Search a Qdrant collection by semantic similarity."""
    client = get_qdrant_client()
    query_embedding = generate_embeddings([query_text])[0]
    results = client.query_points(
        collection_name=collection_name,
        query=query_embedding,
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
