// Phase 2 AC-1: CSV → prepare → join(Postgres) → group builds.
// The recipe graph is assembled via the API (a create-recipe UI is a later slice —
// recorded); the Build action, Flow canvas, and run drawer are driven through the UI.
import AxeBuilder from "@axe-core/playwright";
import { type APIRequestContext, expect, test } from "@playwright/test";
import { APP_ORIGIN, login } from "./helpers";

// Same-origin header so the API's CSRF guard accepts these programmatic writes.
const H = { origin: APP_ORIGIN } as const;

async function api(request: APIRequestContext, method: "post" | "patch", path: string, body: unknown) {
  const res = await request[method](`${APP_ORIGIN}/api/v1${path}`, { data: body, headers: H });
  expect(res.ok(), `${method} ${path} → ${res.status()} ${await res.text()}`).toBeTruthy();
  return res.json();
}

const CSV = "order_id,amount,region\n1,10.0,NL\n2,20.0,BE\n3,30.0,NL\n";

/** Build the CSV → prepare → join(postgres) → group chain; returns the project key. */
async function seedChain(request: APIRequestContext, key: string): Promise<void> {
  await api(request, "post", "/projects", { key, name: key });

  // orders (uploaded CSV)
  const upload = await request.post(`${APP_ORIGIN}/api/v1/projects/${key}/uploads`, {
    headers: H,
    multipart: { file: { name: "o.csv", mimeType: "text/csv", buffer: Buffer.from(CSV) } },
  });
  expect(upload.ok(), await upload.text()).toBeTruthy();
  await api(request, "post", `/projects/${key}/datasets`, {
    name: "orders",
    source: { kind: "upload", upload_id: (await upload.json()).upload_id },
    legal_basis: "demo",
    purpose_codes: ["demo"],
  });

  // sales (the seeded demo_src.sales table, dialed from the API container as postgres:5432)
  const conn = await api(request, "post", `/projects/${key}/connections`, {
    name: "demo-src",
    kind: "postgres",
    config: { host: "postgres", port: 5432, database: "demo_src", user: "osaip" },
    secret: "osaip",
    legal_basis: "demo",
    purpose_codes: ["demo"],
  });
  await api(request, "post", `/projects/${key}/datasets`, {
    name: "sales",
    source: { kind: "table", connection_id: conn.id, table: "public.sales" },
  });

  // prepare(orders → orders_clean): a formula column
  await api(request, "post", `/projects/${key}/recipes`, {
    name: "prep",
    kind: "prepare",
    config: { steps: [{ op: "formula", column: "amount_eur", expression: 'col("amount") * 1.0' }] },
    input_dataset_names: ["orders"],
    output_names: ["orders_clean"],
  });
  // join(orders_clean + sales → joined) on region
  await api(request, "post", `/projects/${key}/recipes`, {
    name: "joiner",
    kind: "join",
    config: { how: "inner", on: [{ left: "region", right: "region" }], right_suffix: "_s" },
    input_dataset_names: ["orders_clean", "sales"],
    output_names: ["joined"],
  });
  // group(joined → summary) by region
  await api(request, "post", `/projects/${key}/recipes`, {
    name: "grouper",
    kind: "group",
    config: {
      by: ["region"],
      aggregations: [{ column: "amount", func: "sum", as: "total" }],
    },
    input_dataset_names: ["joined"],
    output_names: ["summary"],
  });
}

async function waitForJob(request: APIRequestContext, key: string, jobId: string): Promise<any> {
  await expect
    .poll(
      async () => {
        const job = await (
          await request.get(`${APP_ORIGIN}/api/v1/projects/${key}/jobs/${jobId}`)
        ).json();
        return job.status;
      },
      { timeout: 90_000, intervals: [1000] },
    )
    .toMatch(/succeeded|failed|cancelled/);
  return (await request.get(`${APP_ORIGIN}/api/v1/projects/${key}/jobs/${jobId}`)).json();
}

test("the CSV → prepare → join(postgres) → group chain builds and the run drawer shows it", async ({
  page,
}) => {
  await login(page, "admin@osaip.dev");
  const key = `p2b${Date.now()}`;
  await seedChain(page.request, key);

  // The Flow renders the graph.
  await page.goto(`/p/${key}`);
  await expect(page.getByTestId("flow-canvas")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("flow-node").filter({ hasText: "summary" })).toBeVisible();

  // Build the whole chain (build via API to get a deterministic job id, then watch the
  // run drawer reflect it — the Build button is also exercised in 15-stale-rebuild).
  const job = await api(page.request, "post", `/projects/${key}/builds`, { targets: ["summary"] });
  expect(job.steps.length).toBe(3); // prepare + join + group, all never-built

  await page.goto(`/p/${key}?job=${job.id}`);
  await expect(page.getByTestId("run-drawer")).toBeVisible();

  const finished = await waitForJob(page.request, key, job.id);
  expect(finished.status, JSON.stringify(finished.steps)).toBe("succeeded");

  // The group output is built and its sample is per-region totals.
  const sample = await (
    await page.request.get(`${APP_ORIGIN}/api/v1/projects/${key}/datasets/summary/sample`)
  ).json();
  expect(sample.rows.length).toBeGreaterThan(0);
  expect(new Set(sample.rows.map((r: any) => r.region)).size).toBeGreaterThan(0);

  const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  const serious = axe.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""));
  expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
});
