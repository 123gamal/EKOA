"""Shared OpenTelemetry tracing setup — one tracer provider shape reused by
api/ai/worker/mcp, all exporting to the same Tempo backend.

Every span gets the request's ``correlation_id`` (the same contextvar
``ekoa_config.logging`` already threads through every log line) attached as
a span attribute, so a trace in Tempo and its log lines in Loki can be
cross-referenced by the same ID — this is the whole point of standing up
tracing alongside logs/metrics rather than in isolation.
"""

from __future__ import annotations

import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from ekoa_config.logging import correlation_id_var

_CONFIGURED = False


class _CorrelationIdSpanProcessor(SpanProcessor):
    """Stamps the active request's correlation_id onto every span as it
    starts, so traces and logs share one lookup key in Grafana."""

    def on_start(self, span, parent_context=None) -> None:  # noqa: ANN001
        cid = correlation_id_var.get()
        if cid:
            span.set_attribute("correlation_id", cid)

    def on_end(self, span) -> None:  # noqa: ANN001
        pass

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:  # noqa: ARG002
        return True


def setup_tracing(service_name: str, app=None) -> None:  # noqa: ANN001
    """Configure the process-wide tracer provider and (optionally)
    instrument a FastAPI ``app`` + the httpx client library.

    A missing/unreachable OTLP endpoint degrades to spans being created and
    dropped by the exporter's own retry/backoff — it never blocks or crashes
    request handling, so this is safe to enable unconditionally rather than
    gating it behind an extra "is observability enabled" flag.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://tempo:4318")
    provider = TracerProvider(
        resource=Resource.create({SERVICE_NAME: f"ekoa-{service_name}"})
    )
    provider.add_span_processor(_CorrelationIdSpanProcessor())
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
    )
    trace.set_tracer_provider(provider)

    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    HTTPXClientInstrumentor().instrument()

    if app is not None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
