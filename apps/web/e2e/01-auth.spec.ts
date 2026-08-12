import { test, expect } from "@playwright/test";
import { uniqueEmail, E2E_PASSWORD } from "./fixtures/test-data";

// Runs unauthenticated (project "chromium-unauthenticated") — flows 1 and 2.

test("register -> login -> redirected to dashboard", async ({ page }) => {
  const email = uniqueEmail("auth-flow1");

  await page.goto("/register");
  await page.getByLabel("Full Name").fill("Flow One User");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(E2E_PASSWORD);
  await page.getByRole("button", { name: /create account/i }).click();

  await expect(page).toHaveURL(/\/login/);

  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(E2E_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();

  await expect(page).toHaveURL(/\/dashboard/);
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
});

test("unauthenticated visit to a protected route redirects to login, then back after login", async ({
  page,
}) => {
  const email = uniqueEmail("auth-flow2");

  await page.goto("/documents");
  await expect(page).toHaveURL(/\/login\?redirect=/);

  // Register+login this user first (a fresh account, not previously logged in).
  await page.goto("/register");
  await page.getByLabel("Full Name").fill("Flow Two User");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(E2E_PASSWORD);
  await page.getByRole("button", { name: /create account/i }).click();
  await expect(page).toHaveURL(/\/login/);

  // Re-visit the protected route to pick up the redirect= param again.
  await page.goto("/documents");
  await expect(page).toHaveURL(/\/login\?redirect=%2Fdocuments/);

  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(E2E_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();

  await expect(page).toHaveURL(/\/documents/);
});
