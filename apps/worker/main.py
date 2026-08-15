"""EKOA Worker – Celery background task processor."""

from __future__ import annotations

from celery import Celery
from celery.signals import worker_process_init

from ekoa_config.settings import get_settings
from ekoa_config.logging import setup_logging

setup_logging("worker")

settings = get_settings()


@worker_process_init.connect
def _start_metrics_server(**kwargs) -> None:
    """Expose /metrics on a dedicated port when a worker process boots.

    Celery workers aren't ASGI apps (no shared HTTP server to hang a route
    off, unlike api/ai) — ``prometheus_client.start_http_server`` runs its
    own tiny HTTP server in a background thread instead, the standard
    approach for non-web Python processes.
    """
    from prometheus_client import start_http_server

    start_http_server(settings.WORKER_METRICS_PORT)


@worker_process_init.connect
def _start_tracing(**kwargs) -> None:
    """No FastAPI app to instrument here — just the tracer provider +
    httpx instrumentation, so outbound connector API calls get traced."""
    from ekoa_config.tracing import setup_tracing

    setup_tracing("worker")

app = Celery(
    "ekoa-worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Keep our shared JSON handlers; don't let Celery hijack/redirect them.
    worker_hijack_root_logger=False,
    worker_redirect_stdouts=False,
)

# Import tasks so they are registered
import apps.worker.tasks  # noqa: F401, E402


@app.task
def health_check():
    return {"status": "healthy", "service": "ekoa-worker", "version": "0.1.0"}
