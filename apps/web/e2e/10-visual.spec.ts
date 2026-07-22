// Visual smoke (plan §Tests, risk: visual-diff flake ⇒ linux-only baselines).
// Local macOS/Windows runs skip; CI (linux) compares against COMMITTED baselines.
// Until someone generates them (on linux: `playwright test 10-visual
// --update-snapshots`, then commit e2e/10-visual.spec.ts-snapshots/), the specs
// skip instead of failing the whole pipeline on a missing-snapshot error.
import { existsSync } from "node:fs";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { login } from "./helpers";

const BASELINES = join(import.meta.dirname, "10-visual.spec.ts-snapshots");

test.skip(!process.env.CI && process.platform !== "linux", "linux-only baselines");
test.skip(
  !existsSync(BASELINES) && !process.env.UPDATE_SNAPSHOTS,
  "no committed baselines yet — generate with --update-snapshots on linux",
);

const SCREENSHOT_OPTIONS = { maxDiffPixelRatio: 0.02, animations: "disabled" } as const;

test("login page (light)", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByTestId("login-button")).toBeVisible();
  await expect(page).toHaveScreenshot("login-light.png", SCREENSHOT_OPTIONS);
});

test("projects home (dark)", async ({ page }) => {
  await login(page, "admin@osaip.dev");
  await page.getByTestId("user-menu").click();
  await page.getByTestId("theme-dark").click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.getByTestId("projects-table")).toBeVisible();
  await expect(page).toHaveScreenshot("home-dark.png", SCREENSHOT_OPTIONS);
});
