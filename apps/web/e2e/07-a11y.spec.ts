// CP-13: axe scans over the Phase 0 surfaces — zero serious/critical violations.
// Full axe results (all impacts) are attached to the report for triage.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type TestInfo } from "@playwright/test";
import { login } from "./helpers";

async function scan(page: Page, testInfo: TestInfo, slug: string): Promise<void> {
  const results = await new AxeBuilder({ page }).analyze();
  await testInfo.attach(`axe-${slug}`, {
    body: JSON.stringify(results, null, 2),
    contentType: "application/json",
  });
  const severe = results.violations.filter(
    (violation) => violation.impact === "serious" || violation.impact === "critical",
  );
  // Soft: keep scanning the remaining surfaces so one violation doesn't hide others.
  expect
    .soft(
      severe.map((violation) => ({
        id: violation.id,
        impact: violation.impact,
        nodes: violation.nodes.map((node) => node.target),
      })),
      `serious/critical axe violations on ${slug}`,
    )
    .toEqual([]);
}

test("login page has no serious/critical violations", async ({ page }, testInfo) => {
  await page.goto("/login");
  await expect(page.getByTestId("login-button")).toBeVisible();
  await scan(page, testInfo, "login");
});

test("authed surfaces have no serious/critical violations", async ({ page }, testInfo) => {
  test.setTimeout(120_000); // five surfaces behind one Keycloak login
  await login(page, "admin@osaip.dev");

  const surfaces: Array<{ path: string; readyTestId: string; slug: string }> = [
    { path: "/", readyTestId: "projects-table", slug: "projects-home" },
    { path: "/p/demo", readyTestId: "project-home", slug: "project-home" },
    { path: "/p/demo/settings", readyTestId: "project-settings", slug: "project-settings" },
    { path: "/hub", readyTestId: "hub-page", slug: "hub" },
    { path: "/p/demo/agents", readyTestId: "stub-page", slug: "stub-agents" },
  ];

  for (const surface of surfaces) {
    await page.goto(surface.path);
    await expect(page.getByTestId(surface.readyTestId)).toBeVisible();
    await scan(page, testInfo, surface.slug);
  }
});
