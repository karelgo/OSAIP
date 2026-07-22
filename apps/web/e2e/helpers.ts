// Shared login flow through the real Keycloak (realm `osaip`, ADR-0001).
// Every test uses Playwright's default fresh browser context — Keycloak SSO cookies
// and the OSAIP session cookie are context-scoped, so roles never bleed into each
// other and RP-initiated logout semantics can't poison a shared storage state.
import { expect, type Page } from "@playwright/test";

export const KEYCLOAK_ORIGIN = "http://localhost:8081";

/** The app origin — must match the API's OSAIP_PUBLIC_URL for CSRF Origin checks. */
export const APP_ORIGIN = "http://localhost:5173";

export async function login(page: Page, email: string, password = "dev"): Promise<void> {
  await page.goto("/");
  // Unauthenticated: the _authed layout redirects to /login (client-side).
  await page.getByTestId("login-button").click();
  // BFF sends us to Keycloak's hosted login page.
  await page.waitForURL(`${KEYCLOAK_ORIGIN}/**`);
  await page.locator("#username").fill(email);
  await page.locator("#password").fill(password);
  const submit = page.locator("#kc-login").or(page.locator('input[type="submit"]'));
  await submit.first().click();
  // Callback → session cookie → back on the app shell.
  await expect(page.getByTestId("topbar")).toBeVisible({ timeout: 15_000 });
}
