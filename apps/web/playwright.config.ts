// Phase 0 acceptance suite (docs/plans/phase-0.md §Tests): runs against the BUILT
// bundle served by `vite preview` on one origin (5173, /api proxied to :8001) — never
// the dev server, so SSE and cookies behave like production (ADR-0001/0003).
//
// Prereqs: the compose stack (api/keycloak/postgres, seeded) is up and the dev `web`
// container is STOPPED — port 5173 must belong to the preview server, which is why
// reuseExistingServer is hard false.
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: "http://localhost:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "pnpm --filter @osaip/web build && pnpm --filter @osaip/web preview",
    url: "http://localhost:5173",
    timeout: 180_000,
    reuseExistingServer: false,
  },
});
