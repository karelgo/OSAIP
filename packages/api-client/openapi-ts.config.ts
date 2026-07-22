import { defineConfig } from "@hey-api/openapi-ts";

export default defineConfig({
  input: "openapi.json",
  output: { path: "src/generated", clean: true, importFileExtension: null },
  plugins: [
    { name: "@hey-api/client-fetch", runtimeConfigPath: "./src/runtime.ts" },
    "@hey-api/typescript",
    "@hey-api/sdk",
    "@tanstack/react-query",
  ],
});
