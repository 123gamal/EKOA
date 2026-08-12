import { test, expect } from "@playwright/test";
import { createOrgAndWorkspace } from "./fixtures/helpers";

const NAV = [
  { label: "Dashboard", heading: /dashboard/i },
  { label: "AI Chat", heading: /rag ai assistant|no workspace selected/i },
  { label: "Knowledge", heading: /knowledge base documents|no workspace selected/i },
  // Workflows/Analytics show an empty-state heading when the account has no
  // org/workspace yet, and the sidebar links carry no workspace_id — both
  // headings are accepted since navigation reachability is what's tested.
  { label: "Workflows", heading: /agentic workflows|workflows & automation/i },
  { label: "Analytics", heading: /ai observability & analytics/i },
  { label: "Settings", heading: "Settings" },
];

test("sidebar navigation reaches all six protected routes", async ({ page }) => {
  // Six sequential page loads, each potentially slow under the backend's
  // documented concurrency bottleneck — see the timeout comment below.
  test.setTimeout(120_000);

  // Ensure at least one org/workspace exists so Workflows/Analytics render
  // their real content rather than an empty state, regardless of what
  // other spec files have or haven't created yet for the shared user.
  await createOrgAndWorkspace(page);
  await page.goto("/dashboard");

  for (const { label, heading } of NAV) {
    await page.getByRole("link", { name: label, exact: true }).click();
    // Generous timeout: this test runs after the resource-heavy workflow
    // specs and the backend's documented concurrency bottleneck
    // (docs/performance-and-nfrs.md) means even unrelated page loads can
    // queue behind their real LLM calls for a while.
    await expect(page.getByRole("heading", { name: heading }).first()).toBeVisible({
      timeout: 30_000,
    });
  }
});

test("sign out clears the session and protected routes redirect again", async ({ page }) => {
  await page.goto("/dashboard");
  await page.getByRole("button", { name: /sign out/i }).click();

  await expect(page).toHaveURL(/\/login/);

  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login/);
});
