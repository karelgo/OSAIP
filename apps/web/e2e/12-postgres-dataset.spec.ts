// Phase 1 AC-2: register a Postgres table (seeded demo_src.sales) and preview it.
// The connection host is dialed FROM THE API CONTAINER → host `postgres`, port 5432
// (the host-visible localhost:5433 would be unreachable from inside compose).
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { login } from "./helpers";

test("admin registers demo_src.sales via a postgres connection and previews rows", async ({
  page,
}) => {
  await login(page, "admin@osaip.dev");

  // Deep-linkable settings tab (§6.7): the connections tab opens from the URL.
  await page.goto("/p/demo/settings?tab=connections");
  await expect(page.getByTestId("connections-table")).toBeVisible();

  const connectionName = `e2e-demo-src-${Date.now()}`;
  await page.getByTestId("connection-create").click();
  const panel = page.getByTestId("connection-panel");
  await expect(panel).toBeVisible();
  await panel.getByLabel(/name/i).first().fill(connectionName);
  await panel.getByLabel(/host/i).fill("postgres");
  await panel.getByLabel(/port/i).fill("5432");
  await panel.getByLabel(/database/i).fill("demo_src");
  await panel.getByLabel(/user/i).fill("osaip");
  await panel.getByLabel(/password|secret/i).fill("osaip");
  await panel.getByLabel(/legal basis/i).fill("Art 6(1)(e) AVG — demo");
  await panel.getByLabel(/purpose/i).fill("demo");
  await page.getByRole("button", { name: "Create connection" }).click();
  await expect(
    page.getByTestId("connections-table").getByText(connectionName),
  ).toBeVisible();

  // Test-connection succeeds against the live container.
  const testResponse = page.waitForResponse((r) => r.url().includes("/test"));
  await page
    .getByTestId("connection-row")
    .filter({ hasText: connectionName })
    .getByTestId("connection-test")
    .click();
  expect((await testResponse).status()).toBe(200);

  // Register: preview-first via inspect, then create (§6.3(3)).
  await page.goto("/p/demo/datasets");
  await page.getByRole("button", { name: "Register from connection" }).click();
  const register = page.getByTestId("register-panel");
  await expect(register).toBeVisible();
  await register.getByLabel(/connection/i).selectOption({ label: connectionName });
  await register.getByLabel(/table/i).fill("public.sales");
  await page.getByRole("button", { name: "Preview" }).click();
  await expect(page.getByTestId("register-preview")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("register-preview")).toContainText("sale_id");

  const datasetName = `e2e-sales-${Date.now()}`;
  await register.getByLabel(/^name/i).first().fill(datasetName);
  await page.getByRole("button", { name: "Register dataset" }).click();

  await expect(page).toHaveURL(new RegExp(`/p/demo/datasets/${datasetName}`));
  await page.getByTestId("dataset-tab-sample").click();
  await expect(page.getByTestId("dataset-sample-table")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("dataset-sample-table")).toContainText("NL");

  const axe = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa"])
    .analyze();
  const serious = axe.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""));
  expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
});
