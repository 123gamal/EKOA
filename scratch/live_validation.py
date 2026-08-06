"""
EKOA - Comprehensive Live Validation Suite
==========================================
Hits real running servers:
  API  : http://localhost:8000
  AI   : http://localhost:8001
  WEB  : http://localhost:3000 (Next.js proxy)

Validates:
  1.  Health checks (API + AI)
  2.  Auth full flow (register, login, me, refresh, logout)
  3.  Organizations CRUD
  4.  Workspaces CRUD
  5.  Documents upload + list + get + 404
  6.  AI /chat sync (direct to AI service :8001)
  7.  AI /chat/stream SSE (direct to AI service :8001)
  8.  Frontend proxy auth /me via Next.js :3000
  9.  Frontend proxy AI SSE via Next.js :3000
"""

import sys
import json
import time
import requests

# Force UTF-8 output to avoid Windows cp1252 issues
sys.stdout.reconfigure(encoding="utf-8") if hasattr(sys.stdout, "reconfigure") else None

API = "http://localhost:8000"
AI  = "http://localhost:8001"
WEB = "http://localhost:3000"

results = []
errors  = []


def check(label, condition, detail=""):
    if condition:
        results.append(f"[PASS] {label}")
        print(f"[PASS] {label}")
    else:
        results.append(f"[FAIL] {label}")
        errors.append(f"[FAIL] {label}: {str(detail)[:200]}")
        print(f"[FAIL] {label} => {str(detail)[:200]}")


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ──────────────────────────────────────────────────────────────
# 1. HEALTH CHECKS
# ──────────────────────────────────────────────────────────────
section("1. HEALTH CHECKS")

try:
    r = requests.get(f"{API}/health", timeout=5)
    check("API /health -> 200", r.status_code == 200, r.text)
    check("API /health status=healthy", r.json().get("status") == "healthy", r.json())
except Exception as e:
    check("API /health reachable", False, str(e))

try:
    r = requests.get(f"{AI}/health", timeout=5)
    check("AI /health -> 200", r.status_code == 200, r.text)
    check("AI /health status=healthy", r.json().get("status") == "healthy", r.json())
except Exception as e:
    check("AI /health reachable", False, str(e))

try:
    r = requests.get(f"{API}/", timeout=5)
    check("API root / -> 200", r.status_code == 200, r.text)
except Exception as e:
    check("API root / reachable", False, str(e))


# ──────────────────────────────────────────────────────────────
# 2. AUTH FLOW
# ──────────────────────────────────────────────────────────────
section("2. AUTHENTICATION FLOW")

email = f"live_{int(time.time())}@ekoa.io"
password = "LiveTest123!"
token = None
refresh_token = None

try:
    r = requests.post(f"{API}/api/v1/auth/register", json={
        "email": email, "password": password, "full_name": "Live Test User"
    }, timeout=10)
    check("POST /api/v1/auth/register -> 201", r.status_code == 201, r.text[:200])
    if r.status_code == 201:
        user = r.json()
        check("  register: email matches", user.get("email") == email, user)
        check("  register: id present", bool(user.get("id")), user)
except Exception as e:
    check("POST /api/v1/auth/register", False, str(e))

try:
    r = requests.post(f"{API}/api/v1/auth/register", json={
        "email": email, "password": password, "full_name": "Live Test User"
    }, timeout=5)
    check("POST /api/v1/auth/register duplicate -> 409", r.status_code == 409, r.text[:200])
except Exception as e:
    check("POST /api/v1/auth/register duplicate -> 409", False, str(e))

try:
    r = requests.post(f"{API}/api/v1/auth/login", json={
        "email": email, "password": password
    }, timeout=10)
    check("POST /api/v1/auth/login -> 200", r.status_code == 200, r.text[:200])
    if r.status_code == 200:
        data = r.json()
        token = data.get("access_token")
        refresh_token = data.get("refresh_token")
        check("  login: access_token present", bool(token), data)
        check("  login: refresh_token present", bool(refresh_token), data)
        check("  login: token_type=bearer", data.get("token_type") == "bearer", data)
except Exception as e:
    check("POST /api/v1/auth/login", False, str(e))

try:
    r = requests.post(f"{API}/api/v1/auth/login", json={
        "email": email, "password": "WrongPass!"
    }, timeout=5)
    check("POST /api/v1/auth/login bad password -> 401", r.status_code == 401, r.text[:200])
except Exception as e:
    check("POST /api/v1/auth/login bad password -> 401", False, str(e))

headers = {"Authorization": f"Bearer {token}"} if token else {}

try:
    r = requests.get(f"{API}/api/v1/auth/me", headers=headers, timeout=5)
    check("GET /api/v1/auth/me -> 200", r.status_code == 200, r.text[:200])
    if r.status_code == 200:
        me = r.json()
        check("  /me: correct email", me.get("email") == email, me)
        check("  /me: is_active=true", me.get("is_active") is True, me)
except Exception as e:
    check("GET /api/v1/auth/me", False, str(e))

try:
    r = requests.get(f"{API}/api/v1/auth/me", timeout=5)
    check("GET /api/v1/auth/me no-auth -> 401", r.status_code == 401, r.text[:200])
except Exception as e:
    check("GET /api/v1/auth/me no-auth -> 401", False, str(e))

try:
    r = requests.post(f"{API}/api/v1/auth/refresh", json={"refresh_token": refresh_token}, timeout=5)
    check("POST /api/v1/auth/refresh -> 200", r.status_code == 200, r.text[:200])
    if r.status_code == 200:
        new_tokens = r.json()
        token = new_tokens.get("access_token")
        headers = {"Authorization": f"Bearer {token}"}
        check("  refresh: new access_token present", bool(token), new_tokens)
except Exception as e:
    check("POST /api/v1/auth/refresh", False, str(e))


# ──────────────────────────────────────────────────────────────
# 3. ORGANIZATIONS
# ──────────────────────────────────────────────────────────────
section("3. ORGANIZATIONS")
org_id = None
org_slug = None

slug = f"live-org-{int(time.time())}"
try:
    r = requests.post(f"{API}/api/v1/organizations/", json={
        "name": "Live Test Org", "slug": slug, "description": "Created by live validation"
    }, headers=headers, timeout=5)
    check("POST /api/v1/organizations/ -> 201", r.status_code == 201, r.text[:200])
    if r.status_code == 201:
        org = r.json()
        org_id   = org.get("id")
        org_slug = org.get("slug")
        check("  org: id present", bool(org_id), org)
        check("  org: slug matches", org_slug == slug, org)
except Exception as e:
    check("POST /api/v1/organizations/", False, str(e))

try:
    r = requests.get(f"{API}/api/v1/organizations/", headers=headers, timeout=5)
    check("GET /api/v1/organizations/ -> 200", r.status_code == 200, r.text[:200])
    if r.status_code == 200:
        orgs = r.json()
        check("  orgs: returns list", isinstance(orgs, list), type(orgs))
        check("  orgs: contains created org", any(o["id"] == org_id for o in orgs), orgs)
except Exception as e:
    check("GET /api/v1/organizations/", False, str(e))

if org_slug:
    try:
        r = requests.get(f"{API}/api/v1/organizations/{org_slug}", headers=headers, timeout=5)
        check(f"GET /api/v1/organizations/{org_slug} -> 200", r.status_code == 200, r.text[:200])
    except Exception as e:
        check(f"GET /api/v1/organizations/{org_slug}", False, str(e))


# ──────────────────────────────────────────────────────────────
# 4. WORKSPACES
# ──────────────────────────────────────────────────────────────
section("4. WORKSPACES")
ws_id = None

if org_id:
    try:
        r = requests.post(f"{API}/api/v1/workspaces/", json={
            "name": "Live Test Workspace",
            "description": "E2E test workspace",
            "organization_id": org_id
        }, headers=headers, timeout=5)
        check("POST /api/v1/workspaces/ -> 201", r.status_code == 201, r.text[:200])
        if r.status_code == 201:
            ws    = r.json()
            ws_id = ws.get("id")
            check("  ws: id present", bool(ws_id), ws)
            check("  ws: organization_id matches", ws.get("organization_id") == org_id, ws)
    except Exception as e:
        check("POST /api/v1/workspaces/", False, str(e))

    try:
        r = requests.get(f"{API}/api/v1/workspaces/?organization_id={org_id}", headers=headers, timeout=5)
        check("GET /api/v1/workspaces/?organization_id=... -> 200", r.status_code == 200, r.text[:200])
        if r.status_code == 200:
            check("  workspaces: returns list", isinstance(r.json(), list), r.json())
    except Exception as e:
        check("GET /api/v1/workspaces/?organization_id=...", False, str(e))

if ws_id:
    try:
        r = requests.get(f"{API}/api/v1/workspaces/{ws_id}", headers=headers, timeout=5)
        check(f"GET /api/v1/workspaces/{{ws_id}} -> 200", r.status_code == 200, r.text[:200])
    except Exception as e:
        check(f"GET /api/v1/workspaces/{{ws_id}}", False, str(e))


# ──────────────────────────────────────────────────────────────
# 5. DOCUMENTS
# ──────────────────────────────────────────────────────────────
section("5. DOCUMENTS")
doc_id = None

if ws_id:
    try:
        content = b"EKOA live test document. Enterprise knowledge for AI pipeline testing."
        r = requests.post(f"{API}/api/v1/documents/upload",
            data={"workspace_id": ws_id},
            files={"file": ("live_test.txt", content, "text/plain")},
            headers=headers, timeout=10)
        check("POST /api/v1/documents/upload -> 201", r.status_code == 201, r.text[:200])
        if r.status_code == 201:
            doc    = r.json()
            doc_id = doc.get("id")
            check("  doc: id present", bool(doc_id), doc)
            check("  doc: status=PENDING", doc.get("status") == "PENDING", doc)
            check("  doc: workspace_id matches", doc.get("workspace_id") == ws_id, doc)
    except Exception as e:
        check("POST /api/v1/documents/upload", False, str(e))

    try:
        r = requests.get(f"{API}/api/v1/documents/?workspace_id={ws_id}", headers=headers, timeout=5)
        check("GET /api/v1/documents/?workspace_id=... -> 200", r.status_code == 200, r.text[:200])
        if r.status_code == 200:
            check("  docs: returns list", isinstance(r.json(), list), r.json())
    except Exception as e:
        check("GET /api/v1/documents/?workspace_id=...", False, str(e))

if doc_id:
    try:
        r = requests.get(f"{API}/api/v1/documents/{doc_id}", headers=headers, timeout=5)
        check(f"GET /api/v1/documents/{{doc_id}} -> 200", r.status_code == 200, r.text[:200])
    except Exception as e:
        check(f"GET /api/v1/documents/{{doc_id}}", False, str(e))

try:
    r = requests.get(f"{API}/api/v1/documents/00000000-0000-0000-0000-000000000000",
                     headers=headers, timeout=5)
    check("GET /api/v1/documents/nonexistent -> 404", r.status_code == 404, r.text[:200])
except Exception as e:
    check("GET /api/v1/documents/nonexistent -> 404", False, str(e))


# ──────────────────────────────────────────────────────────────
# 6. AI SERVICE – SYNC CHAT (direct :8001)
# ──────────────────────────────────────────────────────────────
section("6. AI SERVICE - SYNC CHAT (direct :8001)")

ai_payload = {
    "workspace_id": ws_id or "00000000-0000-0000-0000-000000000001",
    "message": "What are the key features of EKOA?",
    "history": []
}

try:
    r = requests.post(f"{AI}/api/v1/ai/chat", json=ai_payload, timeout=120)
    check("POST /api/v1/ai/chat -> 200", r.status_code == 200, r.text[:300])
    if r.status_code == 200:
        data = r.json()
        check("  ai/chat: has reply", "reply" in data, list(data.keys()))
        check("  ai/chat: reply is string", isinstance(data.get("reply"), str), type(data.get("reply")))
        check("  ai/chat: has conversation_id", bool(data.get("conversation_id")), data)
        check("  ai/chat: actions is list", isinstance(data.get("actions"), list), data)
        check("  ai/chat: has created_at", bool(data.get("created_at")), data)
        reply_preview = data.get("reply", "")[:200]
        print(f"[INFO] AI reply preview: {reply_preview}")
except Exception as e:
    check("POST /api/v1/ai/chat", False, str(e))


# ──────────────────────────────────────────────────────────────
# 7. AI SERVICE – SSE STREAMING (direct :8001)
# ──────────────────────────────────────────────────────────────
section("7. AI SERVICE - SSE STREAMING (direct :8001)")

try:
    events_seen    = []
    message_parsed = None
    current_evt    = "message"

    with requests.post(f"{AI}/api/v1/ai/chat/stream", json=ai_payload, stream=True, timeout=120) as r:
        check("POST /api/v1/ai/chat/stream -> 200", r.status_code == 200, dict(r.headers))
        check("SSE content-type is text/event-stream",
              "text/event-stream" in r.headers.get("content-type", ""), r.headers.get("content-type"))

        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue
            if line.startswith("event:"):
                current_evt = line[6:].strip()
                if current_evt not in events_seen:
                    events_seen.append(current_evt)
            elif line.startswith("data:"):
                raw = line[5:].strip()
                if raw and raw != "[DONE]" and current_evt == "message":
                    try:
                        message_parsed = json.loads(raw)
                    except Exception:
                        pass
            if "done" in events_seen:
                break

    check("SSE emits agent_start", "agent_start" in events_seen, events_seen)
    check("SSE emits message",     "message"     in events_seen, events_seen)
    check("SSE emits done",        "done"        in events_seen, events_seen)
    print(f"[INFO] SSE events sequence: {events_seen}")

    if message_parsed:
        check("SSE message: has reply",           bool(message_parsed.get("reply")),            message_parsed)
        check("SSE message: has conversation_id", bool(message_parsed.get("conversation_id")), message_parsed)
        check("SSE message: sources is list",     isinstance(message_parsed.get("sources"), list), message_parsed)
        print(f"[INFO] SSE reply preview: {message_parsed.get('reply','')[:200]}")
    else:
        check("SSE message event was received and parsed", False, "no message event data found")

except Exception as e:
    check("POST /api/v1/ai/chat/stream (SSE)", False, str(e))


# ──────────────────────────────────────────────────────────────
# 8. FRONTEND PROXY – Auth /me via Next.js :3000
# ──────────────────────────────────────────────────────────────
section("8. FRONTEND PROXY - Auth /me via Next.js :3000")

try:
    r = requests.get(f"{WEB}/api/v1/auth/me", headers=headers, timeout=10)
    check("GET :3000/api/v1/auth/me -> 200 (via Next.js proxy)", r.status_code == 200, r.text[:200])
    if r.status_code == 200:
        me = r.json()
        check("  proxy /me: correct email", me.get("email") == email, me.get("email"))
except Exception as e:
    check("GET :3000/api/v1/auth/me (proxy)", False, str(e))


# ──────────────────────────────────────────────────────────────
# 9. FRONTEND PROXY – AI SSE via Next.js :3000
# ──────────────────────────────────────────────────────────────
section("9. FRONTEND PROXY - AI /chat/stream via Next.js :3000")

try:
    proxy_events  = []
    proxy_message = None
    current_evt   = "message"

    with requests.post(f"{WEB}/api/v1/ai/chat/stream", json=ai_payload, stream=True, timeout=120) as r:
        check("POST :3000/api/v1/ai/chat/stream -> 200 (via proxy)", r.status_code == 200, dict(r.headers))

        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue
            if line.startswith("event:"):
                current_evt = line[6:].strip()
                if current_evt not in proxy_events:
                    proxy_events.append(current_evt)
            elif line.startswith("data:"):
                raw = line[5:].strip()
                if raw and raw != "[DONE]" and current_evt == "message":
                    try:
                        proxy_message = json.loads(raw)
                    except Exception:
                        pass
            if "done" in proxy_events:
                break

    check("Proxy SSE emits message", "message" in proxy_events, proxy_events)
    check("Proxy SSE emits done",    "done"    in proxy_events, proxy_events)
    print(f"[INFO] Proxy SSE events: {proxy_events}")

    if proxy_message:
        check("Proxy SSE message: has reply", bool(proxy_message.get("reply")), proxy_message)
        print(f"[INFO] Proxy SSE reply preview: {proxy_message.get('reply','')[:200]}")
    else:
        check("Proxy SSE message parsed", False, "no message event via proxy")

except Exception as e:
    check("POST :3000/api/v1/ai/chat/stream (proxy)", False, str(e))


# ──────────────────────────────────────────────────────────────
# 10. LOGOUT
# ──────────────────────────────────────────────────────────────
section("10. LOGOUT")

try:
    r = requests.post(f"{API}/api/v1/auth/logout",
                      json={"refresh_token": refresh_token},
                      headers=headers, timeout=5)
    check("POST /api/v1/auth/logout -> 204", r.status_code == 204, r.text[:200])
except Exception as e:
    check("POST /api/v1/auth/logout", False, str(e))


# ──────────────────────────────────────────────────────────────
# FINAL REPORT
# ──────────────────────────────────────────────────────────────
passed = sum(1 for r in results if r.startswith("[PASS]"))
failed = sum(1 for r in results if r.startswith("[FAIL]"))
total  = len(results)

print(f"\n{'='*60}")
print(f"  EKOA LIVE VALIDATION FINAL REPORT")
print(f"{'='*60}")
print(f"  Total checks : {total}")
print(f"  Passed       : {passed}")
print(f"  Failed       : {failed}")
print(f"{'='*60}")

if errors:
    print("\nFAILED CHECKS DETAIL:")
    for e in errors:
        print(f"  {e}")
else:
    print("\n  ALL CHECKS PASSED - SYSTEM FULLY OPERATIONAL!")

print()
sys.exit(0 if failed == 0 else 1)
