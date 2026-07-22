// AC-2 + AC-4: create a project through the side panel, then find the
// `project.created` entry in the hash-chained audit log.
import { expect, test } from "@playwright/test";
import { login } from "./helpers";

test("admin creates a project and the audit log records it", async ({ page }) => {
  await login(page, "admin@osaip.dev");

  await page.getByTestId("new-project").click();
  await expect(page.getByTestId("create-project-panel")).toBeVisible();

  // Unique per run so reruns never collide with an existing key.
  const name = `E2E ${Date.now()}`;
  await page.getByTestId("project-name-input").fill(name);

  // The key auto-derives from the name; read it back instead of re-deriving.
  const key = await page.getByTestId("project-key-input").inputValue();
  expect(key).toMatch(/^[a-z][a-z0-9_-]+$/);

  await page.getByTestId("create-project-submit").click();

  await expect(page).toHaveURL(new RegExp(`/p/${key}$`));
  await expect(page.getByTestId("project-home")).toBeVisible();
  await expect(page.getByTestId("onboarding-checklist")).toBeVisible();

  // AC-4: the creation shows up in the project audit trail.
  await page.goto(`/p/${key}/settings`);
  await page.getByTestId("audit-tab").click();
  await expect(
    page.getByTestId("audit-row").filter({ hasText: "project.created" }).first(),
  ).toBeVisible();
});
