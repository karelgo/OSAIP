// Phase 2 AC-2: a mid-flow edit rebuilds only the stale subset.
// Build the chain, then edit the JOIN recipe — the build must rebuild join + group
// (downstream) but NOT the untouched prepare step.
import { type APIRequestContext, expect, test } from "@playwright/test";
import { APP_ORIGIN, login } from "./helpers";

const H = { origin: APP_ORIGIN } as const;

async function api(request: APIRequestContext, method: "post" | "patch", path: string, body: unknown) {
  const res = await request[method](`${APP_ORIGIN}/api/v1${path}`, { data: body, headers: H });
  expect(res.ok(), `${method} ${path} → ${res.status()} ${await res.text()}`).toBeTruthy();
  return res.json();
}

const CSV = "order_id,amount,region\n1,10.0,NL\n2,20.0,BE\n3,30.0,NL\n";

async function waitForJob(request: APIRequestContext, key: string, jobId: string): Promise<any> {
  await expect
    .poll(
      async () =>
        (await (await request.get(`${APP_ORIGIN}/api/v1/projects/${key}/jobs/${jobId}`)).json()).status,
      { timeout: 90_000, intervals: [1000] },
    )
    .toMatch(/succeeded|failed|cancelled/);
  return (await request.get(`${APP_ORIGIN}/api/v1/projects/${key}/jobs/${jobId}`)).json();
}

test("editing a mid-flow recipe rebuilds only the stale downstream subset", async ({ page }) => {
  await login(page, "admin@osaip.dev");
  const key = `p2s${Date.now()}`;
  await api(page.request, "post", "/projects", { key, name: key });

  // orders (uploaded)
  const upload = await page.request.post(`${APP_ORIGIN}/api/v1/projects/${key}/uploads`, {
    headers: H,
    multipart: { file: { name: "o.csv", mimeType: "text/csv", buffer: Buffer.from(CSV) } },
  });
  await api(page.request, "post", `/projects/${key}/datasets`, {
    name: "orders",
    source: { kind: "upload", upload_id: (await upload.json()).upload_id },
    legal_basis: "demo",
    purpose_codes: ["demo"],
  });
  // prepare → join(sales) → group, mirroring AC-1 (sales from the seeded demo_src)
  const conn = await api(page.request, "post", `/projects/${key}/connections`, {
    name: "demo-src",
    kind: "postgres",
    config: { host: "postgres", port: 5432, database: "demo_src", user: "osaip" },
    secret: "osaip",
    legal_basis: "demo",
    purpose_codes: ["demo"],
  });
  await api(page.request, "post", `/projects/${key}/datasets`, {
    name: "sales",
    source: { kind: "table", connection_id: conn.id, table: "public.sales" },
  });
  await api(page.request, "post", `/projects/${key}/recipes`, {
    name: "prep",
    kind: "prepare",
    config: { steps: [{ op: "formula", column: "amount_eur", expression: 'col("amount") * 1.0' }] },
    input_dataset_names: ["orders"],
    output_names: ["orders_clean"],
  });
  const join = await api(page.request, "post", `/projects/${key}/recipes`, {
    name: "joiner",
    kind: "join",
    config: { how: "inner", on: [{ left: "region", right: "region" }], right_suffix: "_s" },
    input_dataset_names: ["orders_clean", "sales"],
    output_names: ["joined"],
  });
  await api(page.request, "post", `/projects/${key}/recipes`, {
    name: "grouper",
    kind: "group",
    config: { by: ["region"], aggregations: [{ column: "amount", func: "sum", as: "total" }] },
    input_dataset_names: ["joined"],
    output_names: ["summary"],
  });

  // First build: the full chain (3 steps).
  const first = await api(page.request, "post", `/projects/${key}/builds`, { targets: ["summary"] });
  expect(first.steps.length).toBe(3);
  expect((await waitForJob(page.request, key, first.id)).status).toBe("succeeded");

  // Rebuilding now (nothing changed) does nothing.
  const noop = await api(page.request, "post", `/projects/${key}/builds`, { targets: ["summary"] });
  expect(noop.steps.length).toBe(0);

  // Edit the JOIN recipe (left join instead of inner) → join + group stale, prepare fresh.
  await api(page.request, "patch", `/projects/${key}/recipes/${join.id}`, {
    config: { kind: "join", how: "left", on: [{ left: "region", right: "region" }], right_suffix: "_s" },
  });

  // The Flow shows the affected outputs as stale.
  await page.goto(`/p/${key}`);
  await expect(page.getByTestId("flow-canvas")).toBeVisible({ timeout: 15_000 });

  // Build again → EXACTLY 2 steps (join, group). The prepare is untouched (AC-2).
  const second = await api(page.request, "post", `/projects/${key}/builds`, { targets: ["summary"] });
  const targets = second.steps.map((s: any) => s.target_dataset_name).sort();
  expect(targets).toEqual(["joined", "summary"]);
  expect(second.steps.length).toBe(2);
  expect((await waitForJob(page.request, key, second.id)).status).toBe("succeeded");
});
