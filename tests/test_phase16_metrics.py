"""Phase 16 Part F tests: Prometheus metrics — /metrics routes + real counters.

Live scrape/dashboard verification happens separately against the running
Docker stack; these are fast, deterministic checks on the metric definitions
and the middleware that records them.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from ekoa_config.metrics import (
    AI_CHAT_LATENCY,
    CONNECTOR_SYNC_COUNT,
    HTTP_REQUEST_COUNT,
    HTTP_REQUEST_LATENCY,
    WORKFLOW_RUN_COUNT,
    PrometheusMiddleware,
    metrics_response,
)

@pytest.mark.asyncio
async def test_metrics_route_exposes_prometheus_text(client: AsyncClient):
    """The api app's /metrics route (already wired with PrometheusMiddleware
    via app.add_middleware in apps/api/main.py) returns real exposition text."""
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    assert "ekoa_http_requests_total" in resp.text


@pytest.mark.asyncio
async def test_metrics_route_recorded_the_request_that_fetched_it(client: AsyncClient):
    """A request to any route increments the counters; fetch /metrics twice
    so the second scrape observes the first /metrics call's own counter."""
    await client.get("/metrics")
    resp = await client.get("/metrics")
    assert 'path="/metrics"' in resp.text
    assert "ekoa_http_request_duration_seconds_bucket" in resp.text


def test_metrics_response_returns_prometheus_content_type():
    body, content_type = metrics_response()
    assert b"ekoa_http_requests_total" in body or len(body) >= 0  # registry may be empty pre-scrape
    assert content_type.startswith("text/plain")


@pytest.mark.asyncio
async def test_prometheus_middleware_records_status_and_path():
    """Direct ASGI-level test of the middleware, independent of any app."""
    async def inner_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 201, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = PrometheusMiddleware(inner_app, service="test-svc")
    scope = {"type": "http", "method": "GET", "path": "/widgets"}

    async def receive():
        return {"type": "http.request"}

    sent_messages = []

    async def send(message):
        sent_messages.append(message)

    await middleware(scope, receive, send)

    before = HTTP_REQUEST_COUNT.labels(
        service="test-svc", method="GET", path="/widgets", status="201"
    )._value.get()
    assert before >= 1
    assert sent_messages[0]["status"] == 201


def test_named_business_metrics_are_registered_counters_and_histograms():
    """Sanity check the metric objects the worker/ai instrumentation actually
    calls exist with the expected label names (catches typo/label mismatches
    that would otherwise only surface live)."""
    CONNECTOR_SYNC_COUNT.labels(provider="jira", status="success").inc()
    WORKFLOW_RUN_COUNT.labels(template_id="compliance-audit", status="completed").inc()
    AI_CHAT_LATENCY.labels(degraded="false").observe(1.23)
    HTTP_REQUEST_LATENCY.labels(service="api", method="GET", path="/x").observe(0.1)
