// Runtime config for the generated fetch client. Same-origin API (vite proxy in dev,
// api-served static in e2e/prod) — cookies are first-party; problem+json errors are
// thrown as-is so callers can inspect `status`/`type`/`hint`.
import type { CreateClientConfig } from "./generated/client.gen";

export const createClientConfig: CreateClientConfig = (config) => ({
  ...config,
  baseUrl: "",
  throwOnError: false,
});
