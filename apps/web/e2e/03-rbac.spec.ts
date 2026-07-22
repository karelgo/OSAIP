// AC-3: a viewer gets read-only affordances in the UI AND a 403 from the API.
import { expect, test } from "@playwright/test";
import { APP_ORIGIN, login } from "./helpers";

test("viewer sees read-only settings and the API refuses writes", async ({ page }) => {
  await login(page, "viewer@osaip.dev");

  await page.goto("/p/demo/settings");
  await expect(page.getByTestId("project-settings")).toBeVisible();

  // Capability flags are computed server-side; a viewer never gets write affordances.
  await expect(page.getByTestId("settings-name-input")).toBeDisabled();
  await expect(page.getByTestId("settings-save")).toHaveCount(0);
  await expect(page.getByTestId("archive-project")).toHaveCount(0);

  // Defense in depth: the API itself rejects the mutation with the viewer's own
  // session cookie. Origin header keeps the CSRF middleware out of the picture so
  // the 403 we assert is the RBAC one.
  const response = await page.request.patch("/api/v1/projects/demo", {
    data: { name: "Nope" },
    headers: { Origin: APP_ORIGIN },
  });
  expect(response.status()).toBe(403);
  const problem = (await response.json()) as { type?: string };
  expect(problem.type).toBe("urn:osaip:problem:forbidden");
});
