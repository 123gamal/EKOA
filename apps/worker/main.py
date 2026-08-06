"""EKOA Worker – Celery background task processor."""

from __future__ import annotations

from celery import Celery

from ekoa_config.settings import get_settings
from ekoa_config.logging import setup_logging

setup_logging("worker")

settings = get_settings()

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
