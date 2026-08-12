import path from "node:path";
import { test, expect, type Page } from "@playwright/test";
import { createOrgAndWorkspace } from "./fixtures/helpers";

const SENSITIVE_FILE = path.join(process.cwd(), "e2e", "fixtures", "sensitive-policy.txt");

/**
 * The compliance-audit workflow's PII/GDPR detector (apps/worker/workflow_executor.py
 * _exec_compliance) only pauses for approval when it actually finds sensitive
 * data (email/phone/card/SSN regex matches) in the workspace's documents —
 * on an empty workspace it finds nothing and auto-passes. Uploading a
 * document with a fake email address first makes the approval gate actually
 * trigger, matching real usage rather than the (incorrect) assumption that
 * this step always pauses regardless of content.
 */
async function seedSensitiveDocument(page: Page, workspaceId: string) {
  await page.goto(`/documents?workspace_id=${workspaceId}`);
  await page.waitForLoadState("networkidle");
  await page.locator('input[type="file"]').setInputFiles(SENSITIVE_FILE);
  // Generous timeout: this consistently runs right after a workflow test
  // that just made several real LLM calls, and the backend's documented
  // concurrency bottleneck (docs/performance-and-nfrs.md) means requests
  // unrelated to that prior test can still queue behind it for a while.
  await expect(page.getByText(/uploaded successfully/i)).toBeVisible({ timeout: 45_000 });
}

// Per Phase 10's Locust baseline, AI chat completion P95 is ~68s under even
// light concurrent load on this dev machine (docs/performance-and-nfrs.md) —
// workflow runs go through the same LLM path, so both the per-assertion
// timeout AND the overall per-test timeout (Playwright's default is 30s,
// unaffected by an assertion's own {timeout}) need real headroom.
const RUN_TIMEOUT = 120_000;

/**
 * Template cards and their "Create & Run" buttons are both rendered from the
 * same ordered array (workflows/page.tsx maps `templates` once for the
 * headings, once for the buttons within the same Card) — matching by index
 * between the two role-queried lists avoids depending on any CSS class or
 * DOM-nesting assumption that Part B's redesign might change.
 */
async function createAndRun(page: Page, templateTitleRegex: RegExp) {
  await page.waitForLoadState("networkidle");
  await expect(page.getByRole("heading", { name: /workflow templates/i })).toBeVisible({
    timeout: 30_000,
  });
  const templateHeadings = page.getByRole("heading", { level: 3 });
  await expect(templateHeadings.first()).toBeVisible();
  const count = await templateHeadings.count();
  let targetIndex = -1;
  for (let i = 0; i < count; i++) {
    if (templateTitleRegex.test(await templateHeadings.nth(i).innerText())) {
      targetIndex = i;
      break;
    }
  }
  if (targetIndex === -1) {
    throw new Error(`No workflow template heading matched ${templateTitleRegex}`);
  }
  await page.getByRole("button", { name: /create & run/i }).nth(targetIndex).click();

  await expect(page.getByRole("heading", { name: /create & run workflow/i })).toBeVisible();
  await page.getByRole("button", { name: /create & execute/i }).click();
}

test.describe("workflow create -> run -> approve/reject lifecycle", () => {
  // Headroom for the worst case: seedSensitiveDocument (45s) + createAndRun's
  // template-load wait (30s) + the RUN_TIMEOUT approval/completion wait.
  test.describe.configure({ timeout: RUN_TIMEOUT + 90_000 });


  test("compliance-audit template pauses for approval, and approving resolves it", async ({
    page,
  }) => {
    const { workspaceId } = await createOrgAndWorkspace(page);
    await seedSensitiveDocument(page, workspaceId);
    await page.goto("/workflows");
    await expect(page.getByRole("heading", { name: /agentic workflows/i })).toBeVisible();

    await createAndRun(page, /regulatory compliance & security audit/i);

    await expect(
      page.getByRole("heading", { name: /run paused — awaiting human approval/i })
    ).toBeVisible({ timeout: RUN_TIMEOUT });

    await page.getByRole("button", { name: /^approve$/i }).click();

    await expect(page.getByText(/executed successfully against real infrastructure/i)).toBeVisible({
      timeout: RUN_TIMEOUT,
    });
  });

  test("rejecting an approval-paused run terminates it as REJECTED", async ({ page }) => {
    const { workspaceId } = await createOrgAndWorkspace(page);
    await seedSensitiveDocument(page, workspaceId);
    await page.goto("/workflows");

    await createAndRun(page, /regulatory compliance & security audit/i);

    await expect(
      page.getByRole("heading", { name: /run paused — awaiting human approval/i })
    ).toBeVisible({ timeout: RUN_TIMEOUT });

    await page.getByLabel(/reason \/ comment/i).fill("E2E: intentional rejection");
    await page.getByRole("button", { name: /^reject$/i }).click();

    await expect(page.getByText(/^REJECTED$/)).toBeVisible({ timeout: RUN_TIMEOUT });
  });

  test("doc-ingest-rag template runs to completion, and re-running from history works", async ({
    page,
  }) => {
    await createOrgAndWorkspace(page);
    await page.goto("/workflows");

    await createAndRun(page, /document ingestion & rag indexing pipeline/i);

    await expect(page.getByText(/^COMPLETED$/).first()).toBeVisible({ timeout: RUN_TIMEOUT });

    // Re-run the same workflow from the "Your Workflows" list.
    await page.getByRole("button", { name: /^run$/i }).first().click();

    // Run-history strip (role="group" aria-label="Run history") should now
    // show at least 2 entries.
    const history = page.getByRole("group", { name: /run history/i });
    await expect(history.getByRole("button")).toHaveCount(2, { timeout: RUN_TIMEOUT });
  });
});
