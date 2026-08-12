import { test, expect } from "@playwright/test";

test("home page Sign In and Get Started links navigate correctly", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: /enterprise knowledge/i })).toBeVisible();

  await page.getByRole("link", { name: "Get Started" }).click();
  await expect(page).toHaveURL(/\/register/);

  await page.goBack();
  await page.getByRole("link", { name: "Sign In" }).first().click();
  await expect(page).toHaveURL(/\/login/);
});
