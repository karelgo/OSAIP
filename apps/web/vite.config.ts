import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// One origin for the browser: /api is proxied to the API service in dev AND preview,
// so cookies are first-party and SSE is never split-origin. E2E runs against `vite
// build` + `vite preview` (ADR-0001, plan §Tests). Proxy buffering off for SSE.
const apiTarget = process.env.OSAIP_API_URL ?? "http://localhost:8001";

// http-proxy streams responses unbuffered, so SSE flows through; the API side sets
// Cache-Control: no-cache, no-transform on event streams (ADR-0003).
const proxy = {
  "/api": { target: apiTarget, changeOrigin: false },
} as const;

export default defineConfig({
  plugins: [react()],
  server: { host: true, port: 5173, proxy },
  preview: { host: true, port: 5173, proxy },
});
