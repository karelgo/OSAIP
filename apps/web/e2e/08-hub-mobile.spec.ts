// §6.7: /hub is consumer-facing and must be usable on a phone — visible and free
// of horizontal overflow at 375px.
import { expect, test } from "@playwright/test";
import { login } from "./helpers";

test.use({ viewport: { width: 375, height: 812 } });

test("hub renders on a mobile viewport without horizontal overflow", async ({ page }) => {
  await login(page, "admin@osaip.dev");

  await page.goto("/hub");
  await expect(page.getByTestId("hub-page")).toBeVisible();

  const { scrollWidth, clientWidth } = await page.evaluate(() => {
    const root = document.scrollingElement ?? document.documentElement;
    return { scrollWidth: root.scrollWidth, clientWidth: root.clientWidth };
  });
  expect(scrollWidth, "page must not scroll horizontally").toBeLessThanOrEqual(clientWidth + 1);
});
