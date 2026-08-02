// Phase 3a acceptance: an LLM connection can be created and tested from the UI, the
// call is ledgered, and the Usage panel shows what it cost.
//
// The test goes through the mesh end to end — the "test" button is not a shortcut that
// talks to a provider directly, so a green result here means the residency gate, the
// guardrails, the budget and the ledger all ran.
import { expect, test } from "@playwright/test";
import { login } from "./helpers";

test("an echo connection can be added, tested, and shows up in usage", async ({ page }) => {
  await login(page, "admin@osaip.dev");
  await page.goto("/p/demo/settings?tab=llm");

  // Deep-linkable ?tab= lands directly on the tab (§6.7).
  await expect(page.getByTestId("llm-connections-tab")).toBeVisible();
  // Seed v3 ships one, so the list is never an empty first impression.
  await expect(page.getByTestId("llm-connection-echo-local")).toBeVisible();

  await page.getByTestId("add-llm-connection").click();
  const panel = page.getByTestId("llm-connection-panel");
  await expect(panel).toBeVisible();

  const name = `echo-e2e-${Date.now()}`;
  await page.getByTestId("llm-name").fill(name);
  await page.getByTestId("llm-models").fill("echo-1");
  await page.getByTestId("llm-legal-basis").fill("Art 6(1)(e) AVG — public task");
  await page.getByTestId("llm-purpose-codes").fill("demo.internal");
  await page.getByTestId("llm-save").click();

  await expect(panel).toBeHidden();
  const row = page.getByTestId(`llm-connection-${name}`);
  await expect(row).toBeVisible();
  // A mock must never be mistaken for a real endpoint.
  await expect(row).toContainText("mock");
  await expect(row).toContainText("local");

  // Test it: this really calls the mesh, which really calls the echo provider.
  await row.getByRole("button", { name: "Test" }).click();
  await expect(page.getByText("Connection works").first()).toBeVisible({ timeout: 15_000 });

  // The call is now in the ledger, so the Usage panel can account for it.
  await page.goto("/p/demo/settings?tab=usage");
  await expect(page.getByTestId("usage-panel")).toBeVisible();
  const totals = page.getByTestId("usage-totals");
  await expect(totals).toBeVisible();
  // Echo is priced at zero, so assert on CALLS — the thing that must be non-zero.
  await expect(totals).not.toContainText("0\nCalls");
  await page.getByTestId("usage-group-by").selectOption("model");
  await expect(page.getByTestId("usage-row-echo-1")).toBeVisible();
});

test("the form refuses a hosted vendor declared local, before sending it", async ({ page }) => {
  // Declaring a hosted vendor `local` would silently defeat the CP-11 gate, so the
  // form explains it rather than letting the server 422 be the first hint.
  await login(page, "admin@osaip.dev");
  await page.goto("/p/demo/settings?tab=llm");

  await page.getByTestId("add-llm-connection").click();
  await page.getByTestId("llm-name").fill("openai-wrong");
  await page.getByTestId("llm-provider").selectOption("openai");
  await page.getByTestId("llm-residency").selectOption("local");
  await page.getByTestId("llm-legal-basis").fill("x");
  await page.getByTestId("llm-purpose-codes").fill("y");
  await page.getByTestId("llm-save").click();

  await expect(page.getByText(/declare it external/i)).toBeVisible();
  // Still open: nothing was saved.
  await expect(page.getByTestId("llm-connection-panel")).toBeVisible();
});

test("choosing audit_mode=full says what it retains", async ({ page }) => {
  // The setting that decides whether raw prompt text is kept must not be a silent
  // dropdown — an operator has to see the consequence at the moment they choose it.
  await login(page, "admin@osaip.dev");
  await page.goto("/p/demo/settings?tab=llm");

  await page.getByTestId("add-llm-connection").click();
  await expect(page.getByTestId("audit-full-warning")).toBeHidden();
  await page.getByTestId("llm-audit-mode").selectOption("full");
  await expect(page.getByTestId("audit-full-warning")).toContainText(/raw prompts/i);
  await expect(page.getByTestId("audit-full-warning")).toContainText(/DPIA/i);
});

test("a viewer sees the endpoints but cannot change them", async ({ page }) => {
  // Read-only affordances, not hidden-broken buttons (§6.1).
  await login(page, "viewer@osaip.dev");
  await page.goto("/p/demo/settings?tab=llm");

  await expect(page.getByTestId("llm-connection-echo-local")).toBeVisible();
  await expect(page.getByTestId("add-llm-connection")).toHaveCount(0);
  await expect(page.getByTestId("add-quota")).toHaveCount(0);
});
