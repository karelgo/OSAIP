// Visual smoke (plan §Tests, risk: visual-diff flake ⇒ linux-only baselines).
// Local macOS/Windows runs skip; CI (linux) generates and compares baselines.
// No baselines are committed yet: CI's FIRST run should execute
// `playwright test 10-visual --update-snapshots` once and commit the resulting
// e2e/10-visual.spec.ts-snapshots/ directory; every later run compares against it.
import { expect, test } from "@playwright/test";
import { login } from "./helpers";

test.skip(!process.env.CI && process.platform !== "linux", "linux-only baselines");

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
