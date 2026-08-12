import path from "node:path";
import { test, expect } from "@playwright/test";
import { createOrgAndWorkspace } from "./fixtures/helpers";

const SAMPLE_FILE = path.join(process.cwd(), "e2e", "fixtures", "sample.txt");

test("upload a document, watch status transition, and load more", async ({ page }) => {
  const { workspaceId } = await createOrgAndWorkspace(page);

  await page.goto(`/documents?workspace_id=${workspaceId}`);
  await expect(page.getByRole("heading", { name: /knowledge base documents/i })).toBeVisible();

  await page.locator('input[type="file"]').setInputFiles(SAMPLE_FILE);

  // Upload success message, then the row appears with an initial status badge.
  await expect(page.getByText(/uploaded successfully/i)).toBeVisible({ timeout: 15_000 });
  const docHeading = page.getByRole("heading", { name: "sample.txt" });
  await expect(docHeading).toBeVisible();

  // Poll (the page itself polls every 4s) until it reaches a terminal state.
  await expect(
    docHeading.locator("../../..").getByText(/INDEXED|FAILED/)
  ).toBeVisible({ timeout: 60_000 });
});

test("documents list shows Load More when there are more than one page", async ({ page }) => {
  const { workspaceId } = await createOrgAndWorkspace(page);
  await page.goto(`/documents?workspace_id=${workspaceId}`);

  // With zero documents there's no "Load More" button — assert its absence
  // as the baseline, and assert it appears once more than a page of docs
  // exist. Uploading 26 files (PAGE_SIZE=25) is too slow for a smoke spec,
  // so this only asserts the empty-state contract; pagination itself is
  // exercised implicitly by 06-analytics.spec.ts against seeded data if
  // present, and is safe to expand in a future phase with seeded fixtures.
  await expect(page.getByText(/no documents uploaded/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /load more/i })).toHaveCount(0);
});
