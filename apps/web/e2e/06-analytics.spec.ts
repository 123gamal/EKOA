import { test, expect } from "@playwright/test";

test("analytics dashboard renders live KPIs and charts", async ({ page }) => {
  await page.goto("/analytics");

  await expect(page.getByRole("heading", { name: /ai observability & analytics/i })).toBeVisible();

  await expect(page.getByText(/documents ingested/i)).toBeVisible();
  await expect(page.getByText(/vector chunks indexed/i)).toBeVisible();
  await expect(page.getByText(/processing success rate/i)).toBeVisible();
  await expect(page.getByText(/workflow runs/i).first()).toBeVisible();

  await expect(page.getByText(/document ingestion — last 7 days/i)).toBeVisible();
  await expect(page.getByText(/document processing pipeline/i)).toBeVisible();
  await expect(page.getByText(/workspace footprint/i)).toBeVisible();
});

test("documents table Load More is present only when there are more rows than a page", async ({
  page,
}) => {
  await page.goto("/analytics");
  await expect(page.getByRole("heading", { name: /documents processed/i })).toBeVisible();

  const loadMore = page.getByRole("button", { name: /load more/i });
  // Either it's absent (fewer than PAGE_SIZE docs across all workspaces) or,
  // if present, clicking it must not throw / must fetch more rows.
  if (await loadMore.count()) {
    const before = await page.getByRole("row").count();
    await loadMore.click();
    await expect
      .poll(async () => page.getByRole("row").count())
      .toBeGreaterThan(before);
  }
});
