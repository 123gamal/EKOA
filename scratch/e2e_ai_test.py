"""E2E Live AI Service Test Script for Enterprise Knowledge Operations Assistant (EKOA).

Tests /api/v1/ai/chat and /api/v1/ai/chat/stream endpoints directly.
"""
import sys
import os

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, root)
sys.path.insert(0, os.path.join(root, "packages", "shared-config"))
sys.path.insert(0, os.path.join(root, "packages", "shared-types"))
sys.path.insert(0, os.path.join(root, "packages", "shared-utils"))
sys.path.insert(0, os.path.join(root, "apps", "ai"))

from fastapi.testclient import TestClient
from apps.ai.main import app

def run_ai_e2e_tests():
    client = TestClient(app)
    results = []

    print("\n=== STARTING AI SERVICE END-TO-END TEST SUITE ===")

    # 1. Health check
    res = client.get("/health")
    assert res.status_code == 200, f"Health check failed: {res.text}"
    results.append("GET /health -> 200 OK")

    # 2. Chat Sync endpoint
    chat_payload = {
        "workspace_id": "00000000-0000-0000-0000-000000000001",
        "message": "What is the core architecture of EKOA?",
        "history": []
    }
    res = client.post("/api/v1/ai/chat", json=chat_payload)
    assert res.status_code == 200, f"Chat sync failed: {res.text}"
    data = res.json()
    assert "reply" in data
    assert "conversation_id" in data
    assert isinstance(data["actions"], list)
    results.append("POST /api/v1/ai/chat (Sync) -> 200 OK")

    # 3. Chat Stream (SSE) endpoint
    res = client.post("/api/v1/ai/chat/stream", json=chat_payload)
    assert res.status_code == 200, f"Chat stream failed: {res.text}"
    assert "text/event-stream" in res.headers.get("content-type", "")
    content = res.text
    assert "event: message" in content or "event: agent_start" in content or "data:" in content
    results.append("POST /api/v1/ai/chat/stream (SSE) -> 200 OK")

    print("\n=== SUMMARY OF ALL TESTED AI ENDPOINTS ===")
    for r in results:
        print(f"  [OK] {r}")

    print(f"\nALL {len(results)} AI ENDPOINTS EXECUTED SUCCESSFULLY WITHOUT ERRORS!\n")

if __name__ == "__main__":
    run_ai_e2e_tests()
