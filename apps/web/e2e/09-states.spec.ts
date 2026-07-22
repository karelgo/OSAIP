// §6.7 states checklist: the projects list has a real error state with recovery,
// and a skeleton loading state — exercised by intercepting the projects API.
import { expect, test, type Route } from "@playwright/test";
import { login } from "./helpers";

// Both patterns: the generated client may or may not append a query string, and
// Playwright globs match against the full URL including the query.
const PROJECT_LIST_PATTERNS = ["**/api/v1/projects?**", "**/api/v1/projects"];

const PROBLEM_500 = {
  status: 500,
  contentType: "application/problem+json",
  body: JSON.stringify({
    type: "urn:osaip:problem:internal",
    title: "Internal error",
    status: 500,
    detail: "Injected by the e2e suite.",
    hint: "Retry the request.",
    docs_url: "about:blank",
  }),
};

test("projects error state shows and Retry recovers", async ({ page }) => {
  await login(page, "admin@osaip.dev");

  const fail = async (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill(PROBLEM_500);
  };
  for (const pattern of PROJECT_LIST_PATTERNS) await page.route(pattern, fail);

  await page.goto("/");
  // TanStack Query retries 3 times (~7s of backoff) before surfacing the error.
  await expect(page.getByTestId("projects-error")).toBeVisible({ timeout: 20_000 });

  // Restore the network, then the in-UI Retry must recover without a reload.
  for (const pattern of PROJECT_LIST_PATTERNS) await page.unroute(pattern);
  await page.getByTestId("projects-error").getByRole("button", { name: "Retry" }).click();
  await expect(page.getByTestId("projects-table")).toBeVisible();
});

test("projects loading skeleton shows while the list is pending", async ({ page }) => {
  await login(page, "admin@osaip.dev");

  const delay = async (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await new Promise((resolve) => setTimeout(resolve, 1_500));
    return route.continue();
  };
  for (const pattern of PROJECT_LIST_PATTERNS) await page.route(pattern, delay);

  await page.goto("/");
  await expect(page.getByTestId("projects-loading")).toBeVisible();
  await expect(page.getByTestId("projects-table")).toBeVisible({ timeout: 15_000 });
});
