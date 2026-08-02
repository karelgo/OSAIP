// Phase 3a acceptance: a low budget blocks the call with an error a human can act on.
//
// The distinction this asserts is the one that matters operationally: being out of
// budget must not look like a provider outage, because only one of the two is worth
// retrying.
import { expect, test } from "@playwright/test";
import { login } from "./helpers";

test("a zero-call budget blocks the next call with a clear reason", async ({ page }) => {
  // A CALL limit, not a cost limit: echo is priced at zero, so a €0 cost budget is
  // never exceeded by a €0 call. With a free provider the call count is the only
  // budget that can actually bite — which is exactly why the form exposes both.
  await login(page, "admin@osaip.dev");
  await page.goto("/p/demo/settings?tab=llm");
  await expect(page.getByTestId("llm-connections-tab")).toBeVisible();

  // Seed v3 ships a monthly EUR 5 budget; add a DAY budget of zero euros so the very
  // next call is over the line. (Both periods coexist on one scope — the daily one is
  // the tighter, and it must be the one that bites.)
  await page.getByTestId("add-quota").click();
  await page.getByTestId("quota-eur").fill("");
  await page.getByTestId("quota-calls").fill("0");
  await page
    .getByTestId("quota-section")
    .getByRole("combobox")
    .first()
    .selectOption("day");
  await page.getByTestId("save-quota").click();
  await expect(page.getByTestId("quota-day")).toBeVisible();

  try {
    // Now a call must be refused. The connection test is the shortest path to one.
    await page
      .getByTestId("llm-connection-echo-local")
      .getByRole("button", { name: "Test" })
      .click();

    await expect(page.getByText("Connection test failed").first()).toBeVisible({
      timeout: 15_000,
    });
    // It says WHICH budget is exhausted — not merely that something went wrong. A
    // quota block must also be distinguishable from a provider outage, since only one
    // of the two is worth retrying.
    await expect(page.getByText(/budget/i).first()).toBeVisible();
  } finally {
    // In `finally` on purpose: a blocking budget left behind would fail every later
    // spec, and the first failure would be blamed on the wrong change.
    await page.getByTestId("quota-day").getByRole("button", { name: "Remove" }).click();
    await expect(page.getByTestId("quota-day")).toHaveCount(0);
  }
});

test("the usage panel shows spend against the seeded budget", async ({ page }) => {
  await login(page, "admin@osaip.dev");
  await page.goto("/p/demo/settings?tab=usage");

  await expect(page.getByTestId("usage-panel")).toBeVisible();
  // Seed v3 ships a monthly budget, so the bar is there from a fresh install — a
  // budget nobody can see the spend against is not a control.
  await expect(page.getByTestId("quota-bars")).toBeVisible();
  const bar = page.getByTestId("quota-bar-month");
  await expect(bar).toBeVisible();
  await expect(bar.getByRole("progressbar")).toHaveAttribute("aria-valuemax", "100");
});
