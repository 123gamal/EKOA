import { test, expect } from "@playwright/test";
import { uniqueOrgName, uniqueWorkspaceName, uniqueSuffix } from "./fixtures/test-data";

test("create organization -> create workspace -> navigate to Documents/Chat", async ({ page }) => {
  const orgName = uniqueOrgName();
  const wsName = uniqueWorkspaceName();
  const slug = `e2e-org-${uniqueSuffix()}`;

  await page.goto("/dashboard");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await page.waitForLoadState("networkidle");

  // The dashboard auto-opens this form itself when the account has zero
  // organizations yet — only click the toggle button if it isn't already
  // open, otherwise the click would close it again.
  const orgNameField = page.getByLabel("Organization Name");
  if (!(await orgNameField.isVisible().catch(() => false))) {
    await page.getByRole("button", { name: /new organization/i }).click();
  }
  await orgNameField.fill(orgName);
  await page.getByLabel("Slug").fill(slug);
  await page.getByRole("button", { name: /^create organization$/i }).click();

  await expect(page.getByRole("button", { name: orgName })).toBeVisible();

  // Creating the org auto-opens the workspace form.
  await page.getByLabel("Workspace Name").fill(wsName);
  await page.getByRole("button", { name: /^create workspace$/i }).click();

  const wsCard = page.getByText(wsName).locator("..").locator("..");
  await expect(wsCard.getByRole("link", { name: /documents/i })).toBeVisible();
  await expect(wsCard.getByRole("link", { name: /chat/i })).toBeVisible();

  await wsCard.getByRole("link", { name: /documents/i }).click();
  await expect(page).toHaveURL(/\/documents\?workspace_id=/);
  await expect(page.getByRole("heading", { name: /knowledge base documents/i })).toBeVisible();

  await page.goBack();
  await wsCard.getByRole("link", { name: /chat/i }).click();
  await expect(page).toHaveURL(/\/chat\?workspace_id=/);
  await expect(page.getByRole("heading", { name: /rag ai assistant/i })).toBeVisible();
});
