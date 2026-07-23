// Phase 1 AC-1: CSV upload → preview-first confirm → typed schema + profile.
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { login } from "./helpers";

test("csv upload previews, confirms, and lands on a typed dataset page", async ({ page }) => {
  await login(page, "admin@osaip.dev");
  await page.goto("/p/demo/datasets");
  await expect(page.getByTestId("datasets-table")).toBeVisible();

  await page.getByRole("button", { name: "Upload file" }).click();
  await expect(page.getByTestId("upload-panel")).toBeVisible();
  await page
    .getByTestId("upload-file-input")
    .setInputFiles(new URL("./fixtures/orders.csv", import.meta.url).pathname);

  // Preview-first (§6.3(3) LOCKED): inferred TYPED schema before anything is built.
  await expect(page.getByTestId("upload-preview")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("upload-preview")).toContainText("BIGINT");
  await expect(page.getByTestId("upload-preview")).toContainText("DATE");

  const name = `e2e-upload-${Date.now()}`;
  const panel = page.getByTestId("upload-panel");
  await panel.getByLabel(/name/i).first().fill(name);
  await panel.getByLabel(/legal basis/i).fill("E2E demo data");
  await panel.getByLabel(/purpose/i).fill("demo");
  await page.getByTestId("dataset-create-confirm").click();

  // Lands on the dataset page: typed schema + a stored profile (AC-1).
  await expect(page).toHaveURL(new RegExp(`/p/demo/datasets/${name}`));
  await page.getByTestId("dataset-tab-schema").click();
  await expect(page.getByText("order_id")).toBeVisible();
  await expect(page.getByText("BIGINT").first()).toBeVisible();

  await page.getByTestId("dataset-tab-profile").click();
  // Profile computed at creation: null counts / distincts render without recompute.
  await expect(page.getByTestId("dataset-profile")).toBeVisible();
  await expect(page.getByTestId("dataset-profile")).toContainText("order_id");

  const axe = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa"])
    .analyze();
  const serious = axe.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""));
  expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
});
