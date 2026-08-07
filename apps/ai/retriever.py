"""Qdrant retrieval for the AI agent service."""

from __future__ import annotations

from functools import lru_cache
from qdrant_client import QdrantClient
from qdrant_client.http import models as qdrant_models
from sentence_transformers import SentenceTransformer

from ekoa_config.settings import get_settings

settings = get_settings()


@lru_cache(maxsize=1)
def _get_qdrant() -> QdrantClient:
    return QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)


@lru_cache(maxsize=1)
def _get_embedder() -> SentenceTransformer:
    return SentenceTransformer(settings.EMBEDDING_MODEL_NAME)


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


def retrieve_chunks(
    query: str,
    collection_name: str = "ekoa_default",
    limit: int = 5,
    organization_id: str | None = None,
    workspace_id: str | None = None,
) -> list[dict]:
    """Search Qdrant for chunks relevant to the query, scoped to the tenant."""
    client = _get_qdrant()
    model = _get_embedder()
    query_vector = model.encode([query], show_progress_bar=False)[0].tolist()

    results = client.query_points(
        collection_name=collection_name,
        query=query_vector,
        query_filter=_tenant_filter(organization_id, workspace_id),
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
