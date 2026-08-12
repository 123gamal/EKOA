# EKOA Frontend E2E Tests (Playwright)

## Prerequisite: the backend stack must already be running

Playwright only manages the Next.js dev server. It does **not** start the
9-service Docker Compose backend (postgres/qdrant/redis/api/ai/worker/mcp).
Bring that up first and wait for it to be healthy:

```bash
docker compose -f infrastructure/docker/docker-compose.yml up -d
curl http://localhost:8000/health   # wait until this returns 200
```

If the API's host port (default 8000) is ever blocked locally (this project
has hit Windows dynamic-port-exclusion issues before), override:

```bash
E2E_BASE_URL=http://localhost:3000 NEXT_PUBLIC_API_URL=http://localhost:<port>/api/v1 npm run test:e2e
```

## Running

```bash
cd apps/web
npm run test:e2e          # headless, all specs
npm run test:e2e:ui       # Playwright's interactive UI mode
npm run test:e2e:report   # open the last HTML report
```

## What's covered

Nine spec files covering the 10 identified UI-reachable flows: auth +
middleware redirects, org/workspace creation, document upload + status
polling, chat streaming, the full workflow create→run→approve/reject
lifecycle, analytics, settings/GitHub connector, sidebar navigation +
sign-out, and the home page.

`fixtures/auth.setup.ts` registers and logs in one shared user, saving
`storageState` to `.auth/user.json` (gitignored) so the rest of the specs
reuse an authenticated session instead of driving the login form every
time. `01-auth.spec.ts` runs in a separate unauthenticated project since it
specifically tests the register/login/redirect flows themselves.

`fixtures/test-data.ts` generates unique emails/org/workspace names per run
so repeated local/CI runs never collide on unique DB constraints — the same
pattern `tests/performance/locustfile.py` uses.

## GitHub connector live round-trip (optional)

`07-settings.spec.ts` always tests the connector form's validation, but the
actual connect→sync→disconnect round trip against a real GitHub repo only
runs if `E2E_GITHUB_PAT` is set (plus optionally `E2E_GITHUB_OWNER`/
`E2E_GITHUB_REPO`, defaulting to `octocat/Hello-World`) — same pattern the
project used for Phase 7's live GitHub connector proof.

## Locators

Every spec uses accessible locators (`getByRole`, `getByLabel`, `getByText`)
— never CSS classes or colors — so the suite survives visual redesigns
without needing spec changes.
