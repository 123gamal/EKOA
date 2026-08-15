"""Workflow execution engine - runs real pipeline steps against the live system.

Each template maps to a concrete executor that touches real infrastructure
(PostgreSQL, Qdrant, file parsers, audit log) and returns honest step results.
Only imported by the Celery worker which has torch + qdrant-client installed;
heavy imports are kept lazy so importing this module stays lightweight.
"""

from __future__ import annotations

import re
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ekoa_config.settings import get_settings
from ekoa_config.logging import get_logger
from ekoa_utils.naming import workspace_collection_name

from apps.api.models.document import Document
from apps.api.models.workflow import Workflow, WorkflowRun
from apps.api.models.audit_log import AuditLog

from apps.worker.parsers import parse_file
from apps.worker.chunking import chunk_text

settings = get_settings()
logger = get_logger("worker.workflow_executor")

# --- PII / GDPR detection patterns
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
CARD_RE = re.compile(r"\b(?:\d[ \-]?){13,16}\b")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

# --- Simple rule-based intent classifier for the support router
INTENT_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("Account & Access", ("reset", "login", "password", "account", "access", "authentication", "2fa", "otp", "locked")),
    ("Billing & Orders", ("refund", "order", "shipping", "billing", "invoice", "charge", "payment", "subscribe", "cancel subscription")),
    ("Pricing & Plans", ("pricing", "plan", "cost", "price", "upgrade", "downgrade", "trial", "license")),
    ("Technical Documentation", ("how do i", "how to", "how can", "documentation", "guide", "usage", "setup", "configure", "api", "integration", "sdk", "workflow")),
    ("Security & Compliance", ("security", "compliance", "gdpr", "pii", "audit", "privacy", "data retention", "certificate")),
]


def get_sync_engine():
    url = settings.DATABASE_URL
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    if url.startswith("sqlite+aiosqlite://"):
        url = url.replace("sqlite+aiosqlite://", "sqlite://", 1)
    return create_engine(url, pool_pre_ping=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(logs: list[dict], level: str, message: str) -> None:
    logs.append({"ts": _now_iso(), "level": level, "message": message})


def _step_spec(template_id: str, step_id: str) -> dict:
    from apps.worker.workflow_templates import get_template

    tmpl = get_template(template_id)
    if tmpl:
        for s in tmpl.get("steps", []):
            if s["id"] == step_id:
                return s
    return {"id": step_id, "name": step_id, "type": "agent"}


def _workspace_docs(db: Session, workspace_id: uuid.UUID) -> list[Document]:
    return db.query(Document).filter(Document.workspace_id == workspace_id).all()


# ---------------------------------------------------------------------------
# Executor: Document Ingestion & RAG Indexing Pipeline
# ---------------------------------------------------------------------------
def _exec_ingest(db: Session, wf: Workflow, run: WorkflowRun) -> tuple[list, list, str | None]:
    from apps.worker.embeddings import ensure_collection, generate_embeddings, index_chunks

    workspace_id = wf.workspace_id
    docs = _workspace_docs(db, workspace_id)
    steps: list[dict] = []
    logs: list[dict] = []
    by_status: dict[str, int] = {}
    for d in docs:
        by_status[d.status] = by_status.get(d.status, 0) + 1

    # Step 1 - File Upload Trigger
    t0 = time.perf_counter()
    out = f"Triggered with {len(docs)} document(s) in workspace"
    if docs:
        out += " (" + ", ".join(f"{k}: {v}" for k, v in by_status.items()) + ")"
    steps.append({**_step_spec(wf.template_id, "s1"), "status": "completed", "duration_ms": round((time.perf_counter() - t0) * 1000), "output": out, "data": {"document_count": len(docs), "by_status": by_status}})
    _log(logs, "info", f"File Upload Trigger: {out}")

    if not docs:
        for sid in ("s2", "s3", "s4"):
            steps.append({**_step_spec(wf.template_id, sid), "status": "completed", "duration_ms": 0, "output": "No documents to process", "data": {}})
        _log(logs, "warn", "No documents found in workspace - pipeline completed with no-op")
        return steps, logs, None, None

    # Step 2 - Text Parser Agent
    t0 = time.perf_counter()
    parsed: dict[uuid.UUID, str] = {}
    total_chars = 0
    for d in docs:
        try:
            text = parse_file(d.file_path, d.content_type)
            parsed[d.id] = text
            total_chars += len(text)
        except Exception as e:  # file missing / unreadable
            _log(logs, "warn", f"Parser skipped {d.title}: {e}")
    steps.append({**_step_spec(wf.template_id, "s2"), "status": "completed", "duration_ms": round((time.perf_counter() - t0) * 1000), "output": f"Parsed {len(parsed)} document(s) - extracted {total_chars:,} characters", "data": {"documents": len(parsed), "characters": total_chars}})
    _log(logs, "info", f"Text Parser Agent: extracted {total_chars:,} characters from {len(parsed)} document(s)")

    if not parsed:
        steps.append({**_step_spec(wf.template_id, "s3"), "status": "failed", "duration_ms": 0, "output": "No parseable text - nothing to chunk", "data": {}})
        steps.append({**_step_spec(wf.template_id, "s4"), "status": "failed", "duration_ms": 0, "output": "Skipped - no chunks to index", "data": {}})
        _log(logs, "error", "No parseable text found; chunking and indexing skipped")
        return steps, logs, "No parseable text found in workspace documents", None

    # Step 3 - Semantic Chunker
    t0 = time.perf_counter()
    chunks_by_doc: dict[uuid.UUID, list[str]] = {}
    total_chunks = 0
    for doc_id, text in parsed.items():
        chunks = chunk_text(text)
        chunks_by_doc[doc_id] = chunks
        total_chunks += len(chunks)
    steps.append({**_step_spec(wf.template_id, "s3"), "status": "completed", "duration_ms": round((time.perf_counter() - t0) * 1000), "output": f"Generated {total_chunks:,} overlapping text chunks", "data": {"chunks": total_chunks}})
    _log(logs, "info", f"Semantic Chunker: generated {total_chunks:,} chunks")

    # Step 4 - Qdrant Vector Indexer
    t0 = time.perf_counter()
    collection = workspace_collection_name(workspace_id)
    vector_size = 384
    ensure_collection(collection, vector_size=vector_size)
    indexed_points = 0
    failed_docs = 0
    for doc_id, chunks in chunks_by_doc.items():
        try:
            embeddings = generate_embeddings(chunks) if chunks else []
            count = index_chunks(collection, doc_id, chunks, embeddings)
            indexed_points += count
            doc = db.query(Document).filter(Document.id == doc_id).first()
            if doc:
                doc.status = "INDEXED"
                doc.chunk_count = count
                db.commit()
        except Exception as e:
            failed_docs += 1
            _log(logs, "error", f"Indexer failed for {doc_id}: {e}")
            db.rollback()
    steps.append({**_step_spec(wf.template_id, "s4"), "status": "completed", "duration_ms": round((time.perf_counter() - t0) * 1000), "output": f"Upserted {indexed_points:,} points into {collection}", "data": {"points": indexed_points, "collection": collection, "failed_documents": failed_docs}})
    _log(logs, "success", f"Qdrant Vector Indexer: upserted {indexed_points:,} points into {collection}")

    return steps, logs, None, None


# ---------------------------------------------------------------------------
# Executor: Regulatory Compliance & Security Audit
# ---------------------------------------------------------------------------
def _exec_compliance(db: Session, wf: Workflow, run: WorkflowRun) -> tuple[list, list, str | None]:
    workspace_id = wf.workspace_id
    docs = _workspace_docs(db, workspace_id)
    steps: list[dict] = []
    logs: list[dict] = []

    # Step 1 - Policy Ingestion
    t0 = time.perf_counter()
    texts: dict[uuid.UUID, str] = {}
    total_chars = 0
    for d in docs:
        try:
            text = parse_file(d.file_path, d.content_type)
            texts[d.id] = text
            total_chars += len(text)
        except Exception as e:
            _log(logs, "warn", f"Ingestion skipped {d.title}: {e}")
    steps.append({**_step_spec(wf.template_id, "s1"), "status": "completed", "duration_ms": round((time.perf_counter() - t0) * 1000), "output": f"Ingested {len(texts)} policy document(s) - {total_chars:,} characters", "data": {"documents": len(texts), "characters": total_chars}})
    _log(logs, "info", f"Policy Ingestion: {len(texts)} document(s), {total_chars:,} characters")

    # Step 2 - PII & GDPR Detector
    t0 = time.perf_counter()
    findings = {"email": 0, "phone": 0, "credit_card": 0, "ssn": 0}
    for text in texts.values():
        findings["email"] += len(EMAIL_RE.findall(text))
        findings["phone"] += len(PHONE_RE.findall(text))
        findings["credit_card"] += len(CARD_RE.findall(text))
        findings["ssn"] += len(SSN_RE.findall(text))
    total_findings = sum(findings.values())
    steps.append({**_step_spec(wf.template_id, "s2"), "status": "completed", "duration_ms": round((time.perf_counter() - t0) * 1000), "output": f"Identified {total_findings} potential sensitive data leak(s)", "data": findings})
    _log(logs, "info", f"PII & GDPR Detector: {findings}")

    # Step 3 - Human Approval Gate
    # Phase 5: this is now a real human-in-the-loop decision point. When the
    # detector finds sensitive data the run PAUSES here (status AWAITING_APPROVAL,
    # approval_status PENDING) instead of auto-computing a verdict and continuing.
    # An admin approves or rejects via the API; nothing after this step runs
    # until a decision is recorded.
    t0 = time.perf_counter()
    if total_findings == 0:
        verdict = "PASSED"
        review_out = "No sensitive data found - automated check passed"
        steps.append({**_step_spec(wf.template_id, "s3"), "status": "completed", "duration_ms": round((time.perf_counter() - t0) * 1000), "output": review_out, "data": {"verdict": verdict}})
        _log(logs, "success", f"Human Approval Check: {verdict} - no approval required")
        approval: dict | None = None
    else:
        verdict = "REVIEW_REQUIRED"
        review_out = f"Found {total_findings} potential leak(s) - awaiting human approval"
        steps.append({**_step_spec(wf.template_id, "s3"), "status": "pending_approval", "duration_ms": round((time.perf_counter() - t0) * 1000), "output": review_out, "data": {"verdict": verdict, "findings": findings}})
        _log(logs, "warn", f"Human Approval Check: {verdict} - run paused awaiting approval")
        approval = {"step_id": "s3", "verdict": verdict, "findings": findings}

    # Paused for a human decision: Audit Log Dispatch (s4) must NOT run.
    if approval is not None:
        return steps, logs, None, approval

    # Step 4 - Audit Log Dispatch (real audit log entry)
    t0 = time.perf_counter()
    audit = AuditLog(
        user_id=wf.created_by,
        action="workflow.compliance_audit",
        resource_type="workflows",
        resource_id=wf.id,
        details={
            "run_id": str(run.id),
            "workspace_id": str(workspace_id),
            "verdict": verdict,
            "findings": findings,
            "documents_scanned": len(texts),
        },
    )
    db.add(audit)
    db.commit()
    steps.append({**_step_spec(wf.template_id, "s4"), "status": "completed", "duration_ms": round((time.perf_counter() - t0) * 1000), "output": f"Recorded immutably in Audit Log (id {str(audit.id)[:8]})", "data": {"audit_log_id": str(audit.id)}})
    _log(logs, "success", f"Audit Log Dispatch: wrote audit_logs row {str(audit.id)[:8]}")

    return steps, logs, None, None


# ---------------------------------------------------------------------------
# Executor: Customer Support Query Auto-Router
# ---------------------------------------------------------------------------
def _classify_intent(query: str) -> str:
    lowered = query.lower()
    for intent, keywords in INTENT_RULES:
        for kw in keywords:
            if kw in lowered:
                return intent
    return "General Inquiry"


def _exec_support(db: Session, wf: Workflow, run: WorkflowRun) -> tuple[list, list, str | None]:
    from apps.worker.embeddings import search_collection

    workspace_id = wf.workspace_id
    steps: list[dict] = []
    logs: list[dict] = []
    query = (run.input_json or {}).get("query") or "How do I reset my account password?"
    query = str(query).strip()

    # Step 1 - Incoming Query Event
    t0 = time.perf_counter()
    steps.append({**_step_spec(wf.template_id, "s1"), "status": "completed", "duration_ms": round((time.perf_counter() - t0) * 1000), "output": f"Query received: \"{query}\"", "data": {"query": query}})
    _log(logs, "info", f"Incoming Query Event: \"{query}\"")

    # Step 2 - Intent Classifier Agent
    t0 = time.perf_counter()
    intent = _classify_intent(query)
    steps.append({**_step_spec(wf.template_id, "s2"), "status": "completed", "duration_ms": round((time.perf_counter() - t0) * 1000), "output": f"Classified intent: {intent}", "data": {"intent": intent}})
    _log(logs, "info", f"Intent Classifier: {intent}")

    # Step 3 - Knowledge Search Node
    t0 = time.perf_counter()
    collection = workspace_collection_name(workspace_id)
    retrieved: list[dict] = []
    try:
        retrieved = search_collection(collection, query, limit=5)
    except Exception as e:
        _log(logs, "warn", f"Knowledge Search: could not query {collection} - {e}")
    steps.append({**_step_spec(wf.template_id, "s3"), "status": "completed", "duration_ms": round((time.perf_counter() - t0) * 1000), "output": f"Retrieved {len(retrieved)} matching context passage(s)", "data": {"retrieved": len(retrieved), "collection": collection}})
    _log(logs, "info", f"Knowledge Search Node: {len(retrieved)} passage(s) from {collection}")

    # Step 4 - Response Synthesizer
    t0 = time.perf_counter()
    if retrieved:
        parts = ["Based on the knowledge base:"]
        for r in retrieved[:5]:
            score = r.get("score", 0.0)
            parts.append(f"- \"{r.get('text', '')[:220]}\" (similarity {score:.2f})")
        parts.append("Sources: " + ", ".join(f"doc {r.get('document_id', '')[:8]}" for r in retrieved[:5]))
        response = "\n".join(parts)
        synth_out = f"Generated cited answer from {len(retrieved)} source(s)"
    else:
        response = "No relevant knowledge found in the workspace. Please escalate this inquiry to a human agent."
        synth_out = "No sources found - synthesized fallback escalation notice"
    steps.append({**_step_spec(wf.template_id, "s4"), "status": "completed", "duration_ms": round((time.perf_counter() - t0) * 1000), "output": synth_out, "data": {"response": response, "sources": len(retrieved)}})
    _log(logs, "success", f"Response Synthesizer: {synth_out}")

    return steps, logs, None, None


EXECUTORS: dict[str, callable] = {
    "doc-ingest-rag": _exec_ingest,
    "compliance-audit": _exec_compliance,
    "support-router": _exec_support,
}


def _notify_approval_needed(db: Session, wf: Workflow, run: WorkflowRun) -> None:
    """Best-effort notification to the workflow's creator that a run is
    paused awaiting their decision. Never raises — a notification failure
    must not fail the workflow run itself."""
    try:
        from apps.api.models.user import User
        from apps.api.models.workspace import Workspace
        from apps.api.services import notification_service

        creator = db.query(User).filter(User.id == wf.created_by).first()
        workspace = db.query(Workspace).filter(Workspace.id == wf.workspace_id).first()
        if creator is None:
            return
        notification_service.notify_sync(
            db,
            user_id=creator.id,
            organization_id=workspace.organization_id if workspace else None,
            type="workflow.approval_needed",
            title=f"Approval needed: {wf.name}",
            body=f"A run of '{wf.name}' is paused awaiting your approval.",
            resource_type="workflow_runs",
            resource_id=run.id,
            email_to=creator.email,
        )
    except Exception:  # noqa: BLE001
        logger.warning("workflow_approval_notification_failed", extra={"workflow_id": str(wf.id)})


def _run_workflow_core(db: Session, run_id: str) -> None:
    """Execute (or resume) one workflow run against real infrastructure.

    Returns without a terminal status when the run pauses for human approval:
    the run is left in AWAITING_APPROVAL with ``approval_status=PENDING`` and
    ``completed_at`` unset. The API's approve/reject endpoints continue from
    that state.
    """
    run = db.query(WorkflowRun).filter(WorkflowRun.id == uuid.UUID(run_id)).first()
    if not run:
        return
    wf = db.query(Workflow).filter(Workflow.id == run.workflow_id).first()
    if not wf:
        return

    run.status = "RUNNING"
    run.started_at = datetime.now(timezone.utc)
    wf.status = "RUNNING"
    db.commit()

    executor = EXECUTORS.get(wf.template_id)
    steps: list[dict] = []
    logs: list[dict] = []
    error: str | None = None
    approval: dict | None = None
    if executor is None:
        error = f"Unknown workflow template: {wf.template_id}"
        _log(logs, "error", error)
    else:
        try:
            steps, logs, error, approval = executor(db, wf, run)
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
            _log(logs, "error", error)

    run.steps = steps
    run.logs = logs
    if error:
        run.status = "FAILED"
        run.error = error
        run.completed_at = datetime.now(timezone.utc)
        wf.status = "FAILED"
    elif approval:
        # Pause for a human decision. The run is intentionally left non-terminal
        # (no completed_at) so callers know it has not finished.
        run.status = "AWAITING_APPROVAL"
        run.approval_status = "PENDING"
        run.approval_step_id = approval.get("step_id")
        run.approved_by = None
        run.approved_at = None
        run.approval_reason = None
        wf.status = "AWAITING_APPROVAL"
        _notify_approval_needed(db, wf, run)
    else:
        run.status = "COMPLETED"
        run.completed_at = datetime.now(timezone.utc)
        wf.status = "COMPLETED"
    db.commit()


def run_workflow_sync(run_id: str) -> None:
    """Execute a workflow run end-to-end against real infrastructure."""
    engine = get_sync_engine()
    with Session(engine) as db:
        _run_workflow_core(db, run_id)
