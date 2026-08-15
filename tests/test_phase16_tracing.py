"""Phase 16 Part F tests: OpenTelemetry tracing setup.

Live trace delivery to Tempo is verified separately against the running
Docker stack (no Tempo/network dependency here) — these check the tracer
provider wiring and the correlation_id-stamping span processor directly.
"""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from ekoa_config.logging import correlation_id_var
from ekoa_config.tracing import _CorrelationIdSpanProcessor


def test_correlation_id_span_processor_stamps_active_correlation_id():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(_CorrelationIdSpanProcessor())
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")

    token = correlation_id_var.set("cid-12345")
    try:
        with tracer.start_as_current_span("test-span"):
            pass
    finally:
        correlation_id_var.reset(token)

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].attributes.get("correlation_id") == "cid-12345"


def test_correlation_id_span_processor_noop_without_active_correlation_id():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(_CorrelationIdSpanProcessor())
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")

    with tracer.start_as_current_span("test-span"):
        pass

    spans = exporter.get_finished_spans()
    assert "correlation_id" not in (spans[0].attributes or {})


def test_setup_tracing_is_idempotent_across_calls():
    """A second call must not raise (e.g. double-instrumenting httpx)."""
    from ekoa_config import tracing as tracing_mod

    original = tracing_mod._CONFIGURED
    try:
        tracing_mod._CONFIGURED = False
        tracing_mod.setup_tracing("test-service")
        provider_after_first = trace.get_tracer_provider()
        tracing_mod.setup_tracing("test-service")
        assert trace.get_tracer_provider() is provider_after_first
    finally:
        tracing_mod._CONFIGURED = original
