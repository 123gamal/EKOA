import { test as setup, expect } from "@playwright/test";
import { uniqueEmail, E2E_PASSWORD } from "./test-data";

const authFile = "e2e/.auth/user.json";

/**
 * Registers and logs in one shared user for every authenticated spec.
 * Saves storageState (captures both the localStorage access token that
 * apps/web/src/lib/api.ts reads, and the access_token/refresh cookies that
 * apps/web/src/middleware.ts reads) so specs don't fabricate tokens.
 */
setup("authenticate", async ({ page }) => {
  const email = uniqueEmail("baseline");

  await page.goto("/register");
  await page.getByLabel("Full Name").fill("E2E Baseline User");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(E2E_PASSWORD);
  await page.getByRole("button", { name: /create account/i }).click();

  await expect(page).toHaveURL(/\/login/);

  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(E2E_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();

  await expect(page).toHaveURL(/\/dashboard/);
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();

  await page.context().storageState({ path: authFile });
});
