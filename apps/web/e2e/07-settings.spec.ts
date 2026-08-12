import { test, expect } from "@playwright/test";
import { createOrgAndWorkspace } from "./fixtures/helpers";

test("settings page shows the current user's profile", async ({ page }) => {
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
  await expect(page.getByText("Full Name")).toBeVisible();
  await expect(page.getByText("Email", { exact: true })).toBeVisible();
  await expect(page.getByText("Active")).toBeVisible();
});

test("GitHub connector form validates required fields", async ({ page }) => {
  await createOrgAndWorkspace(page);
  await page.goto("/settings");

  await expect(page.getByRole("heading", { name: /github integration/i })).toBeVisible();
  const connectButton = page.getByRole("button", { name: /connect repository/i });

  // Submitting without owner/repo/token should surface validation errors
  // rather than hitting the API.
  await connectButton.click();
  await expect(page.getByText(/required/i).first()).toBeVisible();
});

test.describe("GitHub connector connect/sync/disconnect (requires E2E_GITHUB_PAT)", () => {
  test.skip(!process.env.E2E_GITHUB_PAT, "Set E2E_GITHUB_PAT to run the live GitHub connect round-trip");

  test("connect, sync, and disconnect a real GitHub repository", async ({ page }) => {
    await createOrgAndWorkspace(page);
    await page.goto("/settings");

    await page.getByLabel("Integration Name").fill("E2E GitHub Connector");
    await page.getByLabel("Repository Owner").fill(process.env.E2E_GITHUB_OWNER ?? "octocat");
    await page.getByLabel("Repository").fill(process.env.E2E_GITHUB_REPO ?? "Hello-World");
    await page.getByLabel("Personal Access Token").fill(process.env.E2E_GITHUB_PAT!);
    await page.getByRole("button", { name: /connect repository/i }).click();

    await expect(page.getByText(/repository connected/i)).toBeVisible({ timeout: 20_000 });

    await page.getByRole("button", { name: /sync now/i }).click();
    await expect(page.getByText(/success|running/i).first()).toBeVisible({ timeout: 30_000 });

    await page.getByRole("button", { name: /disconnect/i }).click();
    await expect(page.getByText(/no integrations connected/i)).toBeVisible({ timeout: 10_000 });
  });
});
