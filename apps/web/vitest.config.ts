import { defineConfig } from "vitest/config";

// Unit tests only — the e2e directory is Playwright's (its specs crash under vitest).
export default defineConfig({
  test: {
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    passWithNoTests: true,
  },
});
