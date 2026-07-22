// AC-1: sign in through Keycloak and land on the projects home.
import { expect, test } from "@playwright/test";
import { login } from "./helpers";

test("admin can sign in via Keycloak and reach the projects home", async ({ page }) => {
  await login(page, "admin@osaip.dev");
  await expect(page.getByTestId("topbar")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible();
});
