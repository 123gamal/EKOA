"""Locust load test for EKOA (Phase 10).

Simulates a realistic mix of authenticated traffic against the Nginx
gateway: each simulated user registers its own organization/workspace once
(``on_start``), then repeatedly lists documents, chats with the AI assistant,
and occasionally uploads a document — weighted roughly to the spec's own
rate-limit table (Chapter 9.15: auth 10/min, chat 60/min, upload 20/min,
search 120/min). There is no standalone full-text search endpoint yet, so
"list documents" (a paginated, filtered read) stands in for the search-class
traffic the spec describes.

Run interactively:
    locust -f tests/performance/locustfile.py --host http://localhost

Run headless (e.g. CI smoke test):
    locust -f tests/performance/locustfile.py --host http://localhost \\
        --headless -u 20 -r 5 -t 60s

See tests/performance/README.md for full instructions and how to read the
results against the spec's targets (docs/performance-and-nfrs.md).
"""

from __future__ import annotations

import random
import uuid

from locust import HttpUser, between, task


class EkoaUser(HttpUser):
    """One simulated organization owner: registers, then uses the platform."""

    wait_time = between(1, 3)

    # Set once on_start succeeds; every task guards on this so a rate-limited
    # or otherwise failed registration degrades to a no-op user rather than
    # raising or (worse) tearing down the whole swarm.
    ready = False

    def on_start(self) -> None:
        unique = uuid.uuid4().hex[:12]
        self.email = f"loadtest-{unique}@example.com"
        self.password = "LoadTest123!"

        register_resp = self.client.post(
            "/api/v1/auth/register",
            json={
                "email": self.email,
                "full_name": f"Load Test {unique}",
                "password": self.password,
                "organization_name": f"Load Test Org {unique}",
            },
            name="/api/v1/auth/register",
        )
        if register_resp.status_code != 201:
            # Expected under high spawn rates: auth:register is rate-limited
            # to 10/min per client IP (Ch.9.15), and every simulated user in
            # a local run shares one IP. This user simply stays idle rather
            # than failing the whole run — see tests/performance/README.md.
            return

        login_resp = self.client.post(
            "/api/v1/auth/login",
            json={"email": self.email, "password": self.password},
            name="/api/v1/auth/login",
        )
        token = login_resp.json().get("access_token")
        self.headers = {"Authorization": f"Bearer {token}"}

        orgs = self.client.get(
            "/api/v1/organizations/", headers=self.headers, name="/api/v1/organizations/"
        ).json()
        self.organization_id = orgs["items"][0]["id"]

        workspace_resp = self.client.post(
            "/api/v1/workspaces/",
            json={"name": f"Load Test Workspace {unique}", "organization_id": self.organization_id},
            headers=self.headers,
            name="/api/v1/workspaces/ [create]",
        )
        self.workspace_id = workspace_resp.json()["id"]
        self.conversation_id = None
        self.ready = True

    @task(6)
    def list_documents(self) -> None:
        """Stands in for the spec's "search" traffic class (120/min)."""
        if not self.ready:
            return
        self.client.get(
            f"/api/v1/documents/?workspace_id={self.workspace_id}&page=1&page_size=20",
            headers=self.headers,
            name="/api/v1/documents/ [list]",
        )

    @task(3)
    def chat(self) -> None:
        """The spec's "chat" traffic class (60/min)."""
        if not self.ready:
            return
        questions = [
            "What documents are available in this workspace?",
            "Summarize the most recent document.",
            "What is EKOA?",
        ]
        payload = {
            "workspace_id": self.workspace_id,
            "message": random.choice(questions),
        }
        if self.conversation_id:
            payload["conversation_id"] = self.conversation_id
        resp = self.client.post(
            "/api/v1/ai/chat", json=payload, headers=self.headers, name="/api/v1/ai/chat"
        )
        if resp.status_code == 200:
            self.conversation_id = resp.json().get("conversation_id")

    @task(1)
    def upload_document(self) -> None:
        """The spec's "upload" traffic class (20/min)."""
        if not self.ready:
            return
        content = f"Load test document {uuid.uuid4().hex}.\n\nThis is synthetic content.".encode()
        self.client.post(
            "/api/v1/documents/upload",
            data={"workspace_id": self.workspace_id},
            files={"file": ("loadtest.txt", content, "text/plain")},
            headers=self.headers,
            name="/api/v1/documents/upload",
        )
