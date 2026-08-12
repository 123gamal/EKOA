import type { Page } from "@playwright/test";
import { uniqueOrgName, uniqueWorkspaceName, uniqueSuffix } from "./test-data";

/**
 * Creates a fresh organization + workspace via the dashboard UI and returns
 * their names plus the workspace_id extracted from the resulting Documents
 * link href. Used by specs that need a workspace to exist but aren't
 * themselves testing org/workspace creation (that's 02-org-workspace.spec.ts).
 */
export async function createOrgAndWorkspace(
  page: Page
): Promise<{ orgName: string; wsName: string; workspaceId: string }> {
  const orgName = uniqueOrgName();
  const wsName = uniqueWorkspaceName();
  const slug = `e2e-org-${uniqueSuffix()}`;

  await page.goto("/dashboard");
  // Let the orgs query resolve (and, if the account has zero orgs, let the
  // dashboard's own auto-open effect fire) before deciding whether the
  // "New Organization" toggle needs a click — checking too early races the
  // effect and can end up clicking the form closed right after it auto-opened.
  await page.waitForLoadState("networkidle");
  const orgNameField = page.getByLabel("Organization Name");
  if (!(await orgNameField.isVisible().catch(() => false))) {
    await page.getByRole("button", { name: /new organization/i }).click();
  }
  await orgNameField.fill(orgName);
  await page.getByLabel("Slug").fill(slug);
  await page.getByRole("button", { name: /^create organization$/i }).click();
  await page.getByRole("button", { name: orgName }).waitFor();

  await page.getByLabel("Workspace Name").fill(wsName);
  await page.getByRole("button", { name: /^create workspace$/i }).click();

  const wsCard = page.getByText(wsName).locator("..");
  const docsLink = wsCard.getByRole("link", { name: /documents/i });
  await docsLink.waitFor();
  const href = await docsLink.getAttribute("href");
  const workspaceId = new URL(href!, page.url()).searchParams.get("workspace_id")!;

  return { orgName, wsName, workspaceId };
}
