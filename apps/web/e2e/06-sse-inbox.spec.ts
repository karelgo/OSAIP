// AC-7: a server-emitted event arrives over the live SSE stream as a toast and an
// inbox item — no page reload anywhere in this test.
import { expect, test } from "@playwright/test";
import { APP_ORIGIN, login } from "./helpers";

test("test event arrives as toast + inbox item over SSE", async ({ page }) => {
  await login(page, "admin@osaip.dev");
  await expect(page.getByTestId("topbar")).toBeVisible();

  // Same-context cookies authenticate this call; the endpoint only exists with
  // OSAIP_DEV=1 (compose sets it). Origin sidesteps the CSRF middleware.
  const response = await page.request.post("/api/v1/dev/emit-test-event", {
    headers: { Origin: APP_ORIGIN },
  });
  expect(response.status()).toBe(200);

  // Toast appears via the SSE bridge (radix toast root has role=status).
  const toast = page
    .getByRole("status")
    .filter({ hasText: "Test event received" })
    .or(page.getByText("Test event received"));
  await expect(toast.first()).toBeVisible();

  // The SSE invalidation refetches the notifications count → unread badge.
  await expect(page.getByTestId("unread-badge")).toBeVisible();

  await page.getByTestId("inbox-button").click();
  await expect(page.getByTestId("inbox-drawer")).toBeVisible();
  await expect(
    page.getByTestId("inbox-item").filter({ hasText: "Test event received" }).first(),
  ).toBeVisible();
});
