import { defineConfig, devices } from "@playwright/test";

/**
 * E2E tests assume the EKOA Docker stack (postgres/qdrant/redis/api/ai/worker/mcp)
 * is already running and healthy:
 *   docker compose -f infrastructure/docker/docker-compose.yml up -d
 * Playwright only manages the Next.js dev server — it has no business owning a
 * 9-service Docker Compose lifecycle. See e2e/README.md.
 */
export default defineConfig({
  testDir: "./e2e",
  // Serial by design: the AI service is CPU-bound and has a documented
  // concurrency bottleneck (Phase 10's Locust baseline measured ~68s P95
  // chat latency under just 8 concurrent users — see
  // docs/performance-and-nfrs.md). Parallel E2E workers compete for the same
  // bottleneck and produce flaky timeouts unrelated to the app itself.
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  // 1 retry locally too: the backend's documented concurrency bottleneck
  // (see the fullyParallel comment above) occasionally makes even unrelated
  // simple requests queue behind slow LLM work from a prior test.
  retries: process.env.CI ? 2 : 1,
  workers: 1,
  reporter: [["html", { open: "never" }], ["list"]],

  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },

  projects: [
    {
      name: "setup",
      testMatch: /auth\.setup\.ts/,
    },
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        storageState: "e2e/.auth/user.json",
      },
      dependencies: ["setup"],
      testIgnore: /01-auth\.spec\.ts/,
    },
    {
      name: "chromium-unauthenticated",
      use: { ...devices["Desktop Chrome"] },
      testMatch: /01-auth\.spec\.ts/,
    },
  ],

  webServer: {
    command: "npm run dev",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
