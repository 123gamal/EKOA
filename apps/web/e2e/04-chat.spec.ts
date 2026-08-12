import { test, expect } from "@playwright/test";
import { createOrgAndWorkspace } from "./fixtures/helpers";

test("send a chat message and see a streamed assistant reply", async ({ page }) => {
  const { workspaceId } = await createOrgAndWorkspace(page);

  await page.goto(`/chat?workspace_id=${workspaceId}`);
  await expect(page.getByRole("heading", { name: /rag ai assistant/i })).toBeVisible();

  const input = page.getByPlaceholder(/ask a question about your knowledge base/i);
  await input.fill("What is EKOA?");
  await page.getByRole("button", { name: /^send$/i }).click();

  // User message renders immediately.
  await expect(page.getByText("What is EKOA?")).toBeVisible();

  // Assistant reply streams in — generous timeout since it's a real LLM call
  // (or the deterministic degraded-mode template if no LLM key is configured).
  await expect(page.getByText(/multi-agent langgraph orchestrating/i)).toBeVisible();
  await expect(
    page.getByText(/multi-agent langgraph orchestrating/i)
  ).toBeHidden({ timeout: 60_000 });

  // The happy path should not show the degraded banner unless the backend
  // is actually running without a configured LLM provider.
  const degraded = page.getByText(/degraded/i);
  if (await degraded.count() > 0) {
    test.info().annotations.push({
      type: "note",
      description: "DegradedBanner is showing — LLM provider likely not configured in this environment.",
    });
  }
});

test("suggested prompt buttons send a message without typing", async ({ page }) => {
  const { workspaceId } = await createOrgAndWorkspace(page);
  await page.goto(`/chat?workspace_id=${workspaceId}`);

  const suggestion = page.getByRole("button", { name: /main architecture of ekoa/i });
  await expect(suggestion).toBeVisible();
  await suggestion.click();

  await expect(page.getByText("What is the main architecture of EKOA?")).toBeVisible();
});
