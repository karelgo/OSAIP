// AC-6: ⌘K finds the seeded dataset object_ref and navigates to its page.
import { expect, test } from "@playwright/test";
import { login } from "./helpers";

test("omnibar search finds sales_orders and opens the dataset page", async ({ page }) => {
  await login(page, "admin@osaip.dev");

  await page.keyboard.press("ControlOrMeta+k");
  const input = page.getByTestId("omnibar-input");
  await expect(input).toBeVisible();
  await input.fill("sales");

  // Click the result rather than pressing Enter: cmdk keeps the previously
  // highlighted (action) item selected while server results stream in, so Enter
  // could race the async search response.
  const result = page
    .getByTestId("omnibar-results")
    .getByRole("option")
    .filter({ hasText: "sales_orders" })
    .first();
  await expect(result).toBeVisible();
  await result.click();

  await expect(page).toHaveURL(/\/p\/demo\/datasets\/sales_orders$/);
  await expect(page.getByTestId("stub-page")).toBeVisible();
});
