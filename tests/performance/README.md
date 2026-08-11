# Load testing (Phase 10)

`locustfile.py` drives a realistic mix of authenticated traffic against the
running EKOA stack: each simulated user registers its own org/workspace, then
repeatedly lists documents, chats with the AI assistant, and occasionally
uploads a document — weighted roughly to the rate-limit table in the spec
(Ch.9.15: auth 10/min, chat 60/min, upload 20/min, search 120/min; document
listing stands in for "search" since no standalone full-text search endpoint
exists yet).

## Prerequisites

- The full stack running locally: `docker compose -f infrastructure/docker/docker-compose.yml up -d`
- `pip install locust` (already in `requirements-dev.txt`)

## Running interactively (with the web UI)

```bash
locust -f tests/performance/locustfile.py --host http://localhost
```

Open http://localhost:8089, set the number of users and spawn rate, and
start the test. Locust's own UI shows live RPS, response times (including
p50/p95/p99), and failure rates per endpoint.

## Running headless (e.g. a quick smoke check)

```bash
locust -f tests/performance/locustfile.py --host http://localhost \
    --headless -u 20 -r 5 -t 60s --csv=locust-results
```

This spawns 20 users at 5 users/second, runs for 60 seconds, and writes
`locust-results_stats.csv` / `locust-results_stats_history.csv` /
`locust-results_failures.csv` you can inspect afterward.

## Reading the results

Compare the reported p95 response times per endpoint against the targets in
[`docs/performance-and-nfrs.md`](../../docs/performance-and-nfrs.md) — e.g.
`/api/v1/ai/chat` against the spec's "AI response completion (P95) < 5s"
target, `/api/v1/documents/ [list]` against "API response (P95) < 300ms
(non-AI)".

## Notes

- `--host` should point at the Nginx gateway (`http://localhost`, port 80)
  so both the `api` and `ai` services are reached through the same base URL
  the frontend actually uses (Nginx routes `/api/v1/ai/*` to the AI service
  and everything else under `/api/v1/*` to the API service). Pointing
  directly at `http://localhost:8000` only exercises the API service.
- This is a smoke/baseline tool, not a comprehensive benchmark suite —
  it establishes a real number where previously there was none. Expanding
  scenario coverage (concurrent document ingestion at scale, sustained
  soak tests, etc.) is left for a future pass once there's a baseline to
  compare against.
