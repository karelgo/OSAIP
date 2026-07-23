// Phase 1 AC-3: bad credentials fail cleanly — a sanitized problem, no secret or
// DSN anywhere in the response body.
import { expect, test } from "@playwright/test";
import { login } from "./helpers";

const WRONG_PASSWORD = "Wrong-Password-E2E-9000";

test("wrong postgres password yields a clean, secret-free error", async ({ page }) => {
  await login(page, "admin@osaip.dev");
  await page.goto("/p/demo/settings?tab=connections");
  await expect(page.getByTestId("connections-table")).toBeVisible();

  const connectionName = `e2e-badcreds-${Date.now()}`;
  await page.getByTestId("connection-create").click();
  const panel = page.getByTestId("connection-panel");
  await panel.getByLabel(/name/i).first().fill(connectionName);
  await panel.getByLabel(/host/i).fill("postgres");
  await panel.getByLabel(/port/i).fill("5432");
  await panel.getByLabel(/database/i).fill("demo_src");
  await panel.getByLabel(/user/i).fill("osaip");
  await panel.getByLabel(/password|secret/i).fill(WRONG_PASSWORD);
  await panel.getByLabel(/legal basis/i).fill("Art 6(1)(e) AVG — demo");
  await panel.getByLabel(/purpose/i).fill("demo");
  await page.getByRole("button", { name: "Create connection" }).click();
  await expect(
    page.getByTestId("connections-table").getByText(connectionName),
  ).toBeVisible();

  const testResponse = page.waitForResponse((r) => r.url().includes("/test"));
  await page
    .getByTestId("connection-row")
    .filter({ hasText: connectionName })
    .getByTestId("connection-test")
    .click();

  const response = await testResponse;
  expect(response.status()).toBe(400);
  const body = await response.text();
  const problem = JSON.parse(body);
  // Clean problem+json with a user hint (AC-3)…
  expect(problem.type).toBe("urn:osaip:problem:connection-auth-failed");
  expect(problem.hint).toBeTruthy();
  // …and no leakage: neither the password nor a DSN appears anywhere.
  expect(body).not.toContain(WRONG_PASSWORD);
  expect(body).not.toContain("postgresql://");

  // The UI surfaces the sanitized message.
  await expect(page.getByText(/credentials were rejected/i)).toBeVisible();
});
