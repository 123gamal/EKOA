import { test } from "@playwright/test";
import { createOrgAndWorkspace } from "./fixtures/helpers";

/**
 * Manual visual spot-check, not part of the functional suite: captures
 * screenshots of key routes in both color schemes so the redesign's
 * glassmorphism/gradient/glow can be reviewed by eye. No golden-image
 * comparison — this phase doesn't set up visual regression tooling.
 */
const ROUTES = ["/", "/dashboard", "/documents", "/chat", "/workflows", "/analytics", "/settings"];

for (const theme of ["light", "dark"] as const) {
  test(`spot-check ${theme}`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: theme });
    const { workspaceId } = await createOrgAndWorkspace(page);

    for (const path of ROUTES) {
      const url = ["/documents", "/chat"].includes(path) ? `${path}?workspace_id=${workspaceId}` : path;
      await page.goto(url);
      await page.waitForLoadState("networkidle");
      const name = path === "/" ? "home" : path.replace("/", "");
      await page.screenshot({ path: `e2e/.screenshots/${theme}-${name}.png`, fullPage: true });
    }
  });
}
