"""EKOA RAG benchmark — real chat against a live AI service (FR-1000).

Sends a fixed set of question/answer pairs derived from the Phase 7 httpx
documentation corpus to the live ``POST /api/v1/ai/chat`` endpoint and scores
each answer by substring matching (a deliberately minimal, honest eval: it
measures retrieval grounding, NOT open-ended answer quality).

The script also queries ``GET /analytics/model-performance`` afterwards and
prints the real aggregated telemetry so the numbers in the Phase 9 report are
traceable to actual persisted ``ai_call_logs`` rows.

Scope note: this is NOT a full RAG evaluation (no Precision@k / nDCG / LLM
judge). It asserts only that the retrieved corpus supports the answer.

Usage:
    python scripts/benchmark_rag.py \
        --api-url http://127.0.0.1:8012 \
        --ai-url http://127.0.0.1:8013 \
        --workspace-id 1f5b3bdb-785e-4f31-8d3f-436965d3b796 \
        --org-id 76a705b3-4442-48a0-9cf5-24f7b348a9d4 \
        --email bench-<tag>@example.com --password strongpassword123

The account is registered via the API, then linked to the target organization
directly in Postgres (via DATABASE_URL from the environment) so it can access
the workspace. Idempotent: if the account already exists it is reused.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid

import httpx


# Q/A pairs from the httpx docs corpus. Expected substrings are chosen to be
# verbatim phrasing present in the source docs so a grounded answer must hit
# them.
QA_PAIRS: list[tuple[str, list[str]]] = [
    (
        "Which environment variable controls the CA bundle HTTPX uses for TLS verification, and what does the trust_env option do?",
        ["SSL_CERT_FILE", "trust_env"],
    ),
    (
        "How do I disable SSL certificate verification entirely in a single request?",
        ["verify=False"],
    ),
    (
        "How can I set a timeout of five seconds on a request?",
        ["timeout=5", "timeout", "5.0"],
    ),
    (
        "How do I enable HTTP/2 support on the client?",
        ["http2=True", "http2"],
    ),
    (
        "How do I send a request through a proxy, for example through a forward proxy?",
        ["proxies", "proxy", "proxies="],
    ),
    (
        "Which exceptions does HTTPX raise for a request that failed to connect or timed out?",
        ["ConnectTimeout", "ConnectError", "TimeoutException"],
    ),
    (
        "How do I set a custom header on a request using the auth option or basic authentication?",
        ["HTTPBasicAuth", "auth=", "Authorization"],
    ),
    (
        "What does the response.raise_for_status() method do?",
        ["raise_for_status"],
    ),
    (
        "How do I make an asynchronous request with an AsyncClient?",
        ["AsyncClient", "async with"],
    ),
    (
        "How can I inspect what headers a response returned?",
        ["response.headers"],
    ),
]


def _register_or_login(client: httpx.Client, email: str, password: str) -> dict:
    """Register (or reuse) an account and return its Bearer auth header + user."""
    register = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "RAG Benchmark"},
    )
    if register.status_code not in (200, 201, 211):
        raise RuntimeError(f"register failed: {register.status_code} {register.text}")
    login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    if login.status_code != 200:
        raise RuntimeError(f"login failed: {login.status_code} {login.text}")
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _link_user_to_org(database_url: str, email: str, org_id: str) -> None:
    """Insert an OrgMember row so the benchmark account can access the workspace."""
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _run() -> None:
        engine = create_async_engine(database_url)
        async with engine.begin() as conn:
            user_id = (await conn.execute(
                text("SELECT id FROM users WHERE email = :email"), {"email": email}
            )).scalar_one()
            await conn.execute(
                text(
                    "INSERT INTO org_members (id, user_id, organization_id, role, created_at, updated_at) "
                    "VALUES (:id, :user_id, :org_id, 'admin', now(), now()) "
                    "ON CONFLICT DO NOTHING"
                ),
                {"id": str(uuid.uuid4()), "user_id": str(user_id), "org_id": org_id},
            )
        await engine.dispose()

    asyncio.run(_run())


def main() -> int:
    parser = argparse.ArgumentParser(description="EKOA RAG benchmark (live chat)")
    parser.add_argument("--api-url", default="http://127.0.0.1:8012")
    parser.add_argument("--ai-url", default="http://127.0.0.1:8013")
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--org-id", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", default="strongpassword123")
    parser.add_argument("--database-url", default="postgresql+asyncpg://ekoa_user:ekoa_secret@localhost:5432/ekoa_db")
    args = parser.parse_args()

    with httpx.Client(base_url=args.api_url, timeout=30) as api:
        headers = _register_or_login(api, args.email, args.password)
        user_id = api.get("/api/v1/auth/me", headers=headers).json()["id"]
        print(f"[bench] account ready: {args.email} ({user_id})")

    _link_user_to_org(args.database_url, args.email, args.org_id)
    print(f"[bench] linked account to org {args.org_id}")

    results: list[dict] = []
    total_ms = 0.0
    hits = 0
    with httpx.Client(base_url=args.ai_url, timeout=120) as ai:
        for q, expected in QA_PAIRS:
            started = time.perf_counter()
            resp = ai.post(
                "/api/v1/ai/chat",
                headers=headers,
                json={"workspace_id": args.workspace_id, "message": q},
            )
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
            total_ms += latency_ms
            body = resp.json()
            reply = body.get("reply", "")
            degraded = bool(body.get("degraded"))
            lower = reply.lower()
            matched = [e for e in expected if e.lower() in lower]
            ok = len(matched) == len(expected)
            hits += int(ok)
            results.append({
                "question": q[:70],
                "latency_ms": latency_ms,
                "degraded": degraded,
                "matched": matched,
                "expected": expected,
                "pass": ok,
                "reply_preview": reply[:160].replace("\n", " "),
            })
            print(f"[{('PASS' if ok else 'FAIL')}] {latency_ms:6.1f}ms "
                  f"{'degraded ' if degraded else ''}{q[:60]}")

    passed = sum(1 for r in results if r["pass"])
    print("\n=== Summary ===")
    print(f"questions: {len(results)}  passed: {passed}  "
          f"hit-rate: {passed}/{len(results)}  "
          f"avg_latency: {total_ms / len(results):.0f} ms")
    print(f"degraded calls: {sum(1 for r in results if r['degraded'])}")

    with httpx.Client(base_url=args.api_url, timeout=30) as api:
        perf = api.get(
            "/api/v1/analytics/model-performance",
            params={"workspace_id": args.workspace_id, "days": 7},
            headers=headers,
        )
        if perf.status_code == 200:
            body = perf.json()
            s = body["summary"]
            print("\n=== Real aggregated telemetry (GET /analytics/model-performance) ===")
            print(json.dumps({
                "calls": s["calls"],
                "avg_latency_ms": s["avg_latency_ms"],
                "p95_latency_ms": s["p95_latency_ms"],
                "total_tokens": s["total_tokens"],
                "prompt_tokens": s["prompt_tokens"],
                "completion_tokens": s["completion_tokens"],
                "degraded_rate": s["degraded_rate"],
                "guardrail_trigger_rate": s["guardrail_trigger_rate"],
                "citation_drop_rate": s["citation_drop_rate"],
                "est_cost_usd": s["est_cost_usd"],
                "cost_is_estimate": s["cost_is_estimate"],
                "providers": s["providers"],
            }, indent=2))
        else:
            print(f"[bench] model-performance endpoint failed: {perf.status_code} {perf.text}")

    print("\n=== Per-question detail ===")
    for r in results:
        print(f"[{('PASS' if r['pass'] else 'FAIL')}] {r['latency_ms']:6.1f}ms "
              f"matched={r['matched']} expected={r['expected']}")
        print(f"    Q: {r['question']}")
        print(f"    A: {r['reply_preview']}")

    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
