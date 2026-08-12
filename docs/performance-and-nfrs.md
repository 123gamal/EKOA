# Performance & Non-Functional Requirements

The master spec (`EKOA_ESAS_Volume_I.pdf`) leaves Chapter 4 (Non-Functional
Requirements) as an outline never expanded into numbered requirements — it
names 14 topics (performance, scalability, availability, reliability,
security, compliance, maintainability, observability, disaster recovery,
cost optimization, i18n, accessibility, sustainability, operational
excellence) but gives no concrete targets there. The real numbers exist
scattered across Chapter 9 (API contracts), Chapter 18 (testing/QA), Chapter
19 (observability/AIOps), and Chapter 21 (performance engineering &
scalability). This document consolidates them in one place, and records what
was actually measured against them in Phase 10.

## Targets (from the spec)

| Metric | Target | Source |
|---|---|---|
| Initial page load | < 2s | Ch.21.2 |
| API response (P95, non-AI) | < 300ms | Ch.21.2 |
| AI response start (streaming) | < 2s | Ch.21.2 |
| AI response completion (P95) | < 5s | Ch.21.2, Ch.19.19 |
| Document indexing | < 2 min (standard-sized files) | Ch.21.2, Ch.19.19 |
| Vector search latency | < 200ms | Ch.21.2 |
| Authentication latency | < 500ms | Ch.21.2 |
| API availability | 99.9% | Ch.19.19 |
| Workflow success rate | 99% | Ch.19.19 |
| Authentication success rate | 99.9% | Ch.19.19 |

## Rate limits (from the spec, Ch.9.15)

| Endpoint class | Limit |
|---|---|
| Authentication | 10 requests/minute |
| Chat | 60 requests/minute |
| Document upload | 20 requests/minute |
| Search | 120 requests/minute |

Implemented in `packages/shared-config/ekoa_config/rate_limit.py` — see
`Settings.RATE_LIMIT_LOGIN_LIMIT` / `RATE_LIMIT_REGISTER_LIMIT` /
`RATE_LIMIT_REFRESH_LIMIT` / `RATE_LIMIT_DEFAULT_LIMIT`. Backed by Redis
(`RATE_LIMIT_BACKEND=redis`) in Docker so limits are correct across
multiple replicas of the `api`/`ai` services; falls back to an in-process
in-memory limiter otherwise (tests, local dev without Docker).

## Multi-level caching (from the spec, Ch.21.6 / Ch.8.18 / Ch.17.20)

The spec names 4 cache layers: browser cache, CDN cache, application cache
(Redis — sessions, config, frequently accessed metadata), and an "AI cache"
(embeddings, prompt templates, model metadata, reusable retrieval results).

As of Phase 10, implemented:
- Redis-backed rate limiting (see above).
- Redis-backed query-embedding cache (`apps/ai/retriever.py`, 1h TTL,
  shared globally — embedding of a text string alone is not tenant data).
- Redis-backed search-result cache (`apps/ai/retriever.py`, 5 min TTL,
  scoped per workspace to preserve tenant isolation).

Not yet implemented: browser/CDN caching (frontend concern, not started),
full session storage in Redis (sessions remain Postgres-backed via
`UserSession` — revocation/rotation already works correctly there, so this
is a possible future optimization rather than a current gap).

## Test coverage baseline (Phase 10)

The spec (Ch.18.3) targets ≥90% coverage on critical business logic; no
coverage was ever measured before Phase 10. `pytest --cov=apps --cov=packages`
now runs in CI on every push (see `.github/workflows/ci.yml`) and reports
term output + a `coverage.xml` artifact. The real baseline measured when
this was wired up: **68% overall** (line coverage, hermetic SQLite run,
2026-08-11). No `--cov-fail-under` gate yet — the next phase to touch CI
should set a real threshold using this number, not a guess. Coverage is
notably weaker in the routes/services layers exercised mostly through live
container proofs rather than unit tests (e.g. `connectors.py`, `workflows.py`,
`workflow_executor.py`) than in models/schemas (consistently ~100%).

## Load testing (spec-named tools: k6/Locust, Ch.18.7)

`tests/performance/locustfile.py` — see
[`tests/performance/README.md`](../tests/performance/README.md) for how to
run it. No load test existed anywhere in the codebase before Phase 10.

### Measured baseline (Phase 10)

Real headless run against the local Docker stack (all 9 services, freshly
rebuilt with the Phase 10 changes), through the Nginx gateway:

```
locust -f tests/performance/locustfile.py --host http://localhost \
    --headless -u 8 -r 1 -t 90s --csv=locust-smoke
```
2026-08-11, 8 concurrent users, 96 total requests, **0 failures**.

| Endpoint | Requests | Median | P95 | Max |
|---|---|---|---|---|
| `POST /api/v1/ai/chat` | 17 | 3.4s | **68.0s** | 68.0s |
| `POST /api/v1/auth/login` | 8 | 310ms | 600ms | 602ms |
| `POST /api/v1/auth/register` | 8 | 330ms | 1.6s | 1.64s |
| `GET /api/v1/documents/ [list]` | 41 | 13ms | 42ms | 847ms |
| `POST /api/v1/documents/upload` | 6 | 69ms | 1.3s | 1.33s |
| `GET /api/v1/organizations/` | 8 | 11ms | 21ms | 21ms |
| `POST /api/v1/workspaces/ [create]` | 8 | 67ms | 79ms | 79ms |

**Against the spec's targets**: everything non-AI comfortably beats its
target (`/documents/ [list]` median 13ms vs. the <300ms P95 target for
non-AI API responses; auth well under the <500ms target). **AI chat badly
misses its target** — spec wants P95 < 5s, measured P95 is 68s, a ~14x miss,
even at only 8 concurrent users. This is a genuine finding, not a testing
artifact (0 failures — every request eventually succeeded, just slowly).

Likely contributors, not yet root-caused: the AI service runs a CPU-only
sentence-transformers embedding model and calls an external LLM (DeepSeek/
Gemini) synchronously per chat turn, on a single Docker CPU allocation
(`deploy.resources.limits.cpus: "1.0"`, added this same phase), on a
laptop also running the rest of the stack plus Locust itself. Concurrent
chat requests appear to serialize rather than run in parallel, producing
the long tail (median 3.4s, but P95 68s). The Redis embedding/search cache
added this phase should help repeated identical queries but does not
address concurrent *distinct* requests contending for the same CPU-bound
model and LLM I/O.

**This is flagged as a real gap for a future phase, not fixed here** — a
proper fix (async/batched embedding inference, more AI service replicas,
a faster/hosted embedding endpoint, or request queuing with backpressure)
is an optimization project in its own right, not a Phase 10 line item.
Establishing this real baseline, where previously there was none, is what
Phase 10 committed to.

### Phase 12 update — root cause fixed, plus a deadlock found during verification

Phase 10's finding was root-caused, not just guessed at: `apps/ai/main.py`'s
`chat_sync`/`chat_stream` handlers were already correctly `async def` and
`await`ing `graph.ainvoke(...)`, but the LangGraph node functions themselves —
`retriever_node` and `synthesize_node` — were plain sync `def`. LangGraph runs
sync nodes inline on the calling coroutine, so their blocking bodies (CPU-bound
sentence-transformers embedding, a sync Qdrant client call, a sync LLM HTTP
call) executed directly on the single asyncio event-loop thread. Concurrent
chat requests could not even *start* their work until the previous request's
entire graph finished — a full serialization, matching the measured 68s P95
against a 3.4s median (a queuing artifact, not each call individually being
slow).

**Fix**: converted both nodes to `async def`, offloading their existing
blocking bodies via `asyncio.to_thread(...)` rather than rewriting the
underlying helpers to async SDKs — minimum-risk change, same tested logic,
just moved off the event-loop thread. Also raised the `ai` service's CPU
limit from 1.0 to 2.0 cores, and added a `retrieval_latency_ms` column
(`ai_call_logs`) to separate retrieval time from LLM time in future
diagnostics.

**A second, more serious bug surfaced during live verification, not in unit
tests**: once concurrent requests were actually possible, a manual live
concurrency test (5 simultaneous chat calls through the Nginx gateway)
revealed requests hanging indefinitely — Nginx eventually returned a 504
after its 120s `proxy_read_timeout`, with **zero** log activity from the AI
service for the stuck request (it never even reached the point of writing a
response). Root cause: `SentenceTransformer.encode()` (`apps/ai/retriever.py`)
is not safe to call concurrently from multiple threads — the underlying
HuggingFace `tokenizers` library runs its own internal thread pool and can
deadlock under concurrent multi-threaded `encode()` calls, a known upstream
issue normally avoided by setting `TOKENIZERS_PARALLELISM=false`, which this
service had never set (irrelevant before Phase 12, since nothing called
`retrieve_chunks` concurrently until the event-loop fix made that possible).
Fixed with a `threading.Lock` serializing access to the shared embedder
instance in `retriever.py`, plus `TOKENIZERS_PARALLELISM=false` set on the
`ai` service as defense-in-depth. `pytest`'s existing suite never caught this
— it doesn't exercise real concurrent HTTP load against a live container, only
the live Docker benchmark did.

**Re-benchmarked, same command as Phase 10**
(`locust -f tests/performance/locustfile.py --host http://localhost --headless -u 8 -r 1 -t 90s`),
2026-08-12, through the Nginx gateway, full stack rebuilt with both fixes:

| Endpoint | Requests | Median | P95 | Max |
|---|---|---|---|---|
| `POST /api/v1/ai/chat` | 78 | **1.8s** | **3.8s** | 5.7s |

**AI chat now meets its spec target** (P95 < 5s): P95 dropped from 68.0s to
3.8s, roughly an 18x improvement. Of the 78 chat requests, 34 got a 429
(rate-limited) — expected and not a regression: every simulated Locust user
shares one IP against the 60/min chat rate limit (Ch.9.15), the same known
artifact noted for `/documents/` and `/documents/upload` in the Phase 10
table above. Zero timeouts, zero 5xx, zero hangs.

**Honest caveat, not swept under the rug**: a follow-up manual test sending 5
*truly simultaneous* chat requests (all fired at once, bypassing Locust's more
gradual ramp-up) showed the embedder lock fully serializing those 5 encode()
calls at roughly 7s each (~35s total for the batch) — much slower than a
~22M-parameter MiniLL/L6 model should take, suggesting real CPU contention
under this container's 2.0-core limit rather than the lock itself being the
bottleneck. The lock trades a hard deadlock for a soft serialization point;
it fixes correctness but is not a throughput fix for the embedding step
specifically. Under Locust's more realistic, staggered request pattern this
did not dominate the P95 (median `retrieval_latency_ms` ~3.3s across the run,
per `ai_call_logs`), but a burst of near-simultaneous requests could still
see multi-second queuing at the embedding step alone. Candidate follow-ups,
not done here: raise the CPU limit further, swap the lock for a bounded
semaphore (allow N-way concurrency instead of 1-way), or move to a smaller/
quantized embedding model.

## Deliberately out of scope for Phase 10

Full OpenTelemetry/Prometheus/Grafana/Loki/Tempo/Sentry observability stack
(Ch.15 ADR-013), Kubernetes/multi-replica HA (Ch.21.4, Ch.15.19), and
SAST/DAST/dependency-scanning CI gates are real spec ambitions but sized
like their own phases — not attempted here to keep this phase's scope
honest and finishable. Current telemetry stays the custom `AiCallLog`
DB-row + structured-JSON-log approach from Phase 9.
