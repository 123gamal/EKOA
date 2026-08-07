"""Workflow template catalog — pure data, importable from both API and Worker.

Defines the runnable automation templates surfaced to users. The actual
execution logic for each template lives in apps.worker.tasks.workflow_executors.
"""

from __future__ import annotations

WORKFLOW_TEMPLATES: list[dict] = [
    {
        "id": "doc-ingest-rag",
        "title": "Document Ingestion & RAG Indexing Pipeline",
        "description": (
            "Extract text from uploaded documents, split into semantically "
            "coherent chunks, generate MiniLM-L6 vector embeddings, and index "
            "them into Qdrant for retrieval."
        ),
        "category": "Knowledge Operations",
        "steps": [
            {"id": "s1", "name": "File Upload Trigger", "type": "trigger"},
            {"id": "s2", "name": "Text Parser Agent", "type": "agent"},
            {"id": "s3", "name": "Semantic Chunker", "type": "agent"},
            {"id": "s4", "name": "Qdrant Vector Indexer", "type": "vector_db"},
        ],
    },
    {
        "id": "compliance-audit",
        "title": "Regulatory Compliance & Security Audit",
        "description": (
            "Scan contracts and policy documents against enterprise GDPR and "
            "PII compliance rules; when sensitive data is found, pause for a "
            "human approval gate before recording the outcome in the audit log."
        ),
        "category": "Compliance",
        "steps": [
            {"id": "s1", "name": "Policy Ingestion", "type": "trigger"},
            {"id": "s2", "name": "PII & GDPR Detector", "type": "agent"},
            {"id": "s3", "name": "Human Approval", "type": "human_approval"},
            {"id": "s4", "name": "Audit Log Dispatch", "type": "action"},
        ],
    },
    {
        "id": "support-router",
        "title": "Customer Support Query Auto-Router",
        "description": (
            "Classify an incoming support inquiry, retrieve the most relevant "
            "knowledge passages from Qdrant, and synthesize a cited response."
        ),
        "category": "Customer Operations",
        "steps": [
            {"id": "s1", "name": "Incoming Query Event", "type": "trigger"},
            {"id": "s2", "name": "Intent Classifier Agent", "type": "agent"},
            {"id": "s3", "name": "Knowledge Search Node", "type": "vector_db"},
            {"id": "s4", "name": "Response Synthesizer", "type": "action"},
        ],
    },
]


def get_template(template_id: str) -> dict | None:
    """Return a template dict or None when the id is unknown."""
    for tmpl in WORKFLOW_TEMPLATES:
        if tmpl["id"] == template_id:
            return tmpl
    return None
